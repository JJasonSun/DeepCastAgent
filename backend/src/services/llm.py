"""轻量 LLM 调用封装。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

from errors import DeepCastError

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


class EmptyLLMResponseError(DeepCastError):
    """LLM 请求成功但返回了空 content，适合作为临时失败重试。"""


class StructuredOutputError(DeepCastError):
    """LLM 返回的结构化输出无法解析或未通过 schema 校验。"""


def is_retryable_api_error(exc: Exception) -> bool:
    """判断 OpenAI 兼容 API 异常是否适合重试。"""
    if isinstance(exc, (EmptyLLMResponseError, StructuredOutputError)):
        return True
    if isinstance(exc, (APIConnectionError, APITimeoutError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES or exc.status_code >= 500
    status_code = getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status_code is None and response is not None:
        status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code in RETRYABLE_STATUS_CODES or status_code >= 500
    exc_name = exc.__class__.__name__.lower()
    if any(token in exc_name for token in ("connection", "connect", "timeout", "temporarily")):
        return True
    return False


def run_with_retry(
    operation: Callable[[], Any],
    *,
    operation_name: str,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
) -> Any:
    """对网络/API 临时失败执行指数退避重试。"""
    attempts = max(0, max_retries) + 1
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            if attempt >= attempts or not is_retryable_api_error(exc):
                raise
            delay = min(max(retry_base_delay, 0.1) * (2 ** (attempt - 1)), 12.0)
            logger.warning(
                "%s failed (%s), retrying %d/%d in %.1fs",
                operation_name,
                exc.__class__.__name__,
                attempt,
                max_retries,
                delay,
            )
            time.sleep(delay)

    raise RuntimeError(f"{operation_name} failed unexpectedly")


def _compact_request_args(args: dict[str, Any]) -> dict[str, Any]:
    """移除 None 参数，避免 OpenAI 兼容服务收到无意义字段。"""
    return {key: value for key, value in args.items() if value is not None}


def _build_json_example(schema: dict[str, Any]) -> Any:
    """根据 JSON Schema 生成最小示例，用于 JSON Output 提示。"""
    schema_type = schema.get("type")
    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        return _build_json_example(schema["anyOf"][0])
    if "enum" in schema and isinstance(schema["enum"], list):
        return schema["enum"][0] if schema["enum"] else ""
    if schema_type == "object":
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        keys = required if required else list(properties.keys())
        return {key: _build_json_example(properties.get(key, {})) for key in keys}
    if schema_type == "array":
        items = schema.get("items", {}) or {}
        return [_build_json_example(items)]
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "string":
        return "string"
    return ""


def build_json_mode_instructions(json_schema: dict[str, Any]) -> str:
    """生成 JSON Output 模式的提示文案（包含 json 关键词与示例）。"""
    example = _build_json_example(json_schema)
    example_text = json.dumps(example, ensure_ascii=False, indent=2)
    return (
        "请严格输出 JSON（json）对象，仅返回 JSON，不要附加解释或代码块。\n"
        "Example JSON Output:\n"
        f"{example_text}\n"
        "确保输出是可被 json.loads 解析的合法 JSON。"
    )


def _matches_json_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    return True


def validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """轻量 JSON Schema 校验，覆盖项目当前使用的 type/required/enum/items/properties。"""
    errors: list[str] = []

    if "anyOf" in schema and isinstance(schema["anyOf"], list):
        branch_errors = [validate_json_schema(value, branch, path) for branch in schema["anyOf"]]
        if not any(not item for item in branch_errors):
            errors.append(f"{path}: does not match anyOf")
        return errors

    schema_type = schema.get("type")
    if isinstance(schema_type, str) and not _matches_json_type(value, schema_type):
        errors.append(f"{path}: expected {schema_type}, got {type(value).__name__}")
        return errors

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append(f"{path}: expected one of {enum_values}, got {value!r}")

    if isinstance(value, dict):
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        for key in required:
            if key not in value:
                errors.append(f"{path}.{key}: required field missing")
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, dict):
                errors.extend(validate_json_schema(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if isinstance(min_items, int) and len(value) < min_items:
            errors.append(f"{path}: expected at least {min_items} items, got {len(value)}")
        if isinstance(max_items, int) and len(value) > max_items:
            errors.append(f"{path}: expected at most {max_items} items, got {len(value)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate_json_schema(item, item_schema, f"{path}[{index}]"))

    return errors


def _is_thinking_enabled(extra_body: dict[str, Any] | None) -> bool:
    """判断当前请求是否启用了 DeepSeek thinking mode。"""
    if not isinstance(extra_body, dict):
        return False
    thinking = extra_body.get("thinking")
    return isinstance(thinking, dict) and thinking.get("type") == "enabled"


def call_llm(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    extra_body: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    timeout: float | None = None,
) -> str:
    """同步调用 LLM 并返回完整文本（重试耗尽后抛出 EmptyLLMResponseError，不再静默返回空串）。"""
    request_args: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "extra_body": extra_body,
        "reasoning_effort": reasoning_effort,
        "timeout": timeout,
    }
    if not _is_thinking_enabled(extra_body):
        request_args["temperature"] = temperature
    if tools is not None:
        request_args["tools"] = tools
    if tool_choice is not None:
        request_args["tool_choice"] = tool_choice

    request_args = _compact_request_args(request_args)

    def create_completion() -> str:
        response = client.chat.completions.create(**request_args)
        choice = response.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            logger.warning(
                "LLM completion (%s) returned empty content (finish_reason=%s)",
                model,
                getattr(choice, "finish_reason", None),
            )
            raise EmptyLLMResponseError("LLM completion returned empty content")
        return content

    # 重试耗尽后，run_with_retry 会再次抛出 EmptyLLMResponseError（已是 DeepCastError 子类），
    # 让调用方根据语义自行决定兜底（如 reporter 把空响应视为生成失败）。
    return run_with_retry(
        create_completion,
        operation_name=f"LLM completion ({model})",
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
    )


def call_llm_json(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    model: str,
    json_schema: dict[str, Any],
    schema_name: str = "output",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    extra_body: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    timeout: float | None = None,
    response_transform: Callable[[Any], Any] | None = None,
) -> dict[str, Any] | list:
    """使用 DeepSeek JSON Output 调用 LLM，返回解析后的 JSON 对象。

    重试耗尽后抛出 ``EmptyLLMResponseError``（空内容）或 ``StructuredOutputError``
    （无法解析或 schema 不匹配），二者均为 ``DeepCastError`` 子类，可被 SSE 层统一捕获。
    """
    json_mode_hint = build_json_mode_instructions(json_schema)
    system_prompt = f"{system_prompt.strip()}\n\n{json_mode_hint}"
    request_args: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "extra_body": extra_body,
        "reasoning_effort": reasoning_effort,
        "timeout": timeout,
    }
    if not _is_thinking_enabled(extra_body):
        request_args["temperature"] = temperature

    request_args = _compact_request_args(request_args)

    def create_json_completion() -> dict[str, Any] | list:
        response = client.chat.completions.create(**request_args)
        choice = response.choices[0]
        content = choice.message.content or ""
        if not content.strip():
            logger.warning(
                "LLM JSON completion (%s) returned empty content (finish_reason=%s)",
                model,
                getattr(choice, "finish_reason", None),
            )
            raise EmptyLLMResponseError("LLM JSON completion returned empty content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            logger.error("Structured output returned invalid JSON: %s", content[:500])
            raise StructuredOutputError("Structured output returned invalid JSON") from exc
        if response_transform is not None:
            parsed = response_transform(parsed)
        schema_errors = validate_json_schema(parsed, json_schema)
        if schema_errors:
            logger.error("Structured output failed schema validation: %s", "; ".join(schema_errors[:8]))
            raise StructuredOutputError("Structured output failed schema validation")
        return parsed

    # 重试耗尽后抛出 EmptyLLMResponseError / StructuredOutputError（均为 DeepCastError 子类），
    # 调用方可按需捕获并决定是否走兜底路径。
    return run_with_retry(
        create_json_completion,
        operation_name=f"LLM JSON completion ({model})",
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
    )


def stream_llm(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    extra_body: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    max_retries: int = 3,
    retry_base_delay: float = 1.0,
    timeout: float | None = None,
) -> Generator[str, None, None]:
    """流式调用 LLM，逐块 yield 文本片段。"""
    request_args: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "stream": True,
        "extra_body": extra_body,
        "reasoning_effort": reasoning_effort,
        "timeout": timeout,
    }
    if not _is_thinking_enabled(extra_body):
        request_args["temperature"] = temperature
    if tools is not None:
        request_args["tools"] = tools
    if tool_choice is not None:
        request_args["tool_choice"] = tool_choice

    request_args = _compact_request_args(request_args)
    stream = run_with_retry(
        lambda: client.chat.completions.create(**request_args),
        operation_name=f"LLM stream ({model})",
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content


class LLMClient:
    """封装 OpenAI 客户端 + 配置，提供三个签名明确的方法。

    用法::

        client = LLMClient(openai_client, config)
        text = client.chat_text("你是研究助手", "分析量子计算趋势")
        data = client.chat_json("你是分析员", "输出 JSON", json_schema=schema)
        for chunk in client.stream_text("你是播客主持", "生成脚本"):
            ...

    ``chat_text`` / ``stream_text`` 重试耗尽后会抛出 ``EmptyLLMResponseError``；
    ``chat_json`` 会抛出 ``EmptyLLMResponseError`` 或 ``StructuredOutputError``。
    二者均为 ``DeepCastError`` 子类，可被 SSE 层统一捕获。
    """

    def __init__(self, client: OpenAI, config: Configuration) -> None:
        self._client = client
        self._config = config

    def chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> str:
        """纯文本 LLM 调用，返回完整文本。

        重试耗尽后抛出 ``EmptyLLMResponseError``，调用方需自行决定兜底（如 reporter
        把空报告视为生成失败）。
        """
        # thinking mode 下模型输出更长，自动增加 max_tokens 避免截断
        if enable_thinking and max_tokens <= 4096:
            max_tokens = 8192
        return call_llm(
            client=self._client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._config.active_llm_model(),
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=self._config.build_thinking_body(enable=enable_thinking),
            reasoning_effort=self._config.build_reasoning_effort(enable=enable_thinking),
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
            timeout=timeout,
            **kwargs,
        )

    def stream_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> Generator[str, None, None]:
        """流式 LLM 调用，逐块 yield 文本片段。"""
        return stream_llm(
            client=self._client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._config.active_llm_model(),
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=self._config.build_thinking_body(enable=enable_thinking),
            reasoning_effort=self._config.build_reasoning_effort(enable=enable_thinking),
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
            timeout=timeout,
            **kwargs,
        )

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        *,
        schema_name: str = "output",
        temperature: float = 0.0,
        max_tokens: int = 4096,
        enable_thinking: bool = False,
        timeout: float | None = None,
        response_transform: Callable[[Any], Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | list:
        """JSON Output 模式调用，返回解析后的 dict/list。

        重试耗尽后抛出 ``EmptyLLMResponseError`` 或 ``StructuredOutputError``，不再静默
        返回 ``None``。
        """
        # thinking mode 下模型输出更长，自动增加 max_tokens 避免截断
        if enable_thinking and max_tokens <= 4096:
            max_tokens = 8192
        return call_llm_json(
            client=self._client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self._config.active_llm_model(),
            json_schema=json_schema,
            schema_name=schema_name,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=self._config.build_thinking_body(enable=enable_thinking),
            reasoning_effort=self._config.build_reasoning_effort(enable=enable_thinking),
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
            timeout=timeout,
            response_transform=response_transform,
            **kwargs,
        )

    # ── Legacy 别名（向后兼容，待调用方迁移完成后删除） ──────────────

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        json_schema: dict[str, Any] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> str | dict[str, Any] | list | Generator[str, None, None]:
        """已废弃：统一入口。请改用 chat_text / chat_json / stream_text。"""
        if json_schema is not None:
            return self.chat_json(system_prompt, user_prompt, json_schema, **kwargs)
        if stream:
            return self.stream_text(system_prompt, user_prompt, **kwargs)
        return self.chat_text(system_prompt, user_prompt, **kwargs)


if TYPE_CHECKING:
    from config import Configuration
