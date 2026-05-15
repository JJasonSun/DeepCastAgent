"""轻量 LLM 调用封装。"""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)


def call_llm(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> str:
    """同步调用 LLM 并返回完整文本。"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
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
) -> dict[str, Any] | list | None:
    """使用结构化输出调用 LLM，返回解析后的 JSON 对象。

    基于 XGrammar 约束解码，保证输出 100% 符合给定 schema。
    """
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "schema": json_schema,
            },
        },
    )
    content = response.choices[0].message.content
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("Structured output returned invalid JSON: %s", content[:500])
        return None


def stream_llm(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.0,
    max_tokens: int = 4096,
) -> Generator[str, None, None]:
    """流式调用 LLM，逐块 yield 文本片段。"""
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta if chunk.choices else None
        if delta and delta.content:
            yield delta.content
