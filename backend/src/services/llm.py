"""轻量 LLM 调用封装，替代 HelloAgents 的 HelloAgentsLLM。"""

from __future__ import annotations

import logging
from collections.abc import Generator

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
