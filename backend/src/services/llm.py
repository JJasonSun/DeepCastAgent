"""轻量 LLM 调用封装。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Generator
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
    RateLimitError,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def is_retryable_api_error(exc: Exception) -> bool:
    """判断 OpenAI 兼容 API 异常是否适合重试。"""
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
    """同步调用 LLM 并返回完整文本。"""
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
    response = run_with_retry(
        lambda: client.chat.completions.create(**request_args),
        operation_name=f"LLM completion ({model})",
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
    )
    return response.choices[0].message.content or ""


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
) -> dict[str, Any] | list | None:
    """使用 DeepSeek JSON Output 调用 LLM，返回解析后的 JSON 对象。"""
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
    response = run_with_retry(
        lambda: client.chat.completions.create(**request_args),
        operation_name=f"LLM JSON completion ({model})",
        max_retries=max_retries,
        retry_base_delay=retry_base_delay,
    )
    content = response.choices[0].message.content
    if not content:
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Structured output returned invalid JSON: %s", content[:500])
        return None
    if response_transform is not None:
        parsed = response_transform(parsed)
    schema_errors = validate_json_schema(parsed, json_schema)
    if schema_errors:
        logger.error("Structured output failed schema validation: %s", "; ".join(schema_errors[:8]))
        return None
    return parsed


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
