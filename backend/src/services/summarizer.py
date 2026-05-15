"""任务总结工具。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Callable

from openai import OpenAI

from config import Configuration
from models import SummaryState, TodoItem
from prompts import task_summarizer_system_prompt
from services.llm import call_llm, stream_llm
from services.notes import build_note_guidance
from services.text_processing import strip_tool_calls
from utils import strip_thinking_tokens


class SummarizationService:
    """处理同步和流式任务总结。"""

    def __init__(
        self,
        client: OpenAI,
        config: Configuration,
    ) -> None:
        self._client = client
        self._config = config

    def summarize_task(self, state: SummaryState, task: TodoItem, context: str) -> str:
        """使用 LLM 生成特定于任务的总结。"""
        prompt = self._build_prompt(state, task, context)

        response = call_llm(
            client=self._client,
            system_prompt=task_summarizer_system_prompt.strip(),
            user_prompt=prompt,
            model=self._config.fast_llm_model,
        )

        summary_text = response.strip()
        if self._config.strip_thinking_tokens:
            summary_text = strip_thinking_tokens(summary_text)

        summary_text = strip_tool_calls(summary_text).strip()

        return summary_text or "暂无可用信息"

    def stream_task_summary(
        self, state: SummaryState, task: TodoItem, context: str
    ) -> tuple[Iterator[str], Callable[[], str]]:
        """流式传输任务的总结文本，同时收集完整输出。"""
        prompt = self._build_prompt(state, task, context)
        remove_thinking = self._config.strip_thinking_tokens
        raw_buffer = ""
        visible_output = ""
        emit_index = 0

        def flush_visible() -> Iterator[str]:
            """处理缓冲区，提取并 yield 所有不在 <think>...</think> 块中的可见文本。"""
            nonlocal emit_index, raw_buffer
            while True:
                start = raw_buffer.find("<think>", emit_index)
                if start == -1:
                    if emit_index < len(raw_buffer):
                        segment = raw_buffer[emit_index:]
                        emit_index = len(raw_buffer)
                        if segment:
                            yield segment
                    break

                if start > emit_index:
                    segment = raw_buffer[emit_index:start]
                    emit_index = start
                    if segment:
                        yield segment

                end = raw_buffer.find("</think>", start)
                if end == -1:
                    break
                emit_index = end + len("</think>")

        def generator() -> Iterator[str]:
            nonlocal raw_buffer, visible_output, emit_index
            for chunk in stream_llm(
                client=self._client,
                system_prompt=task_summarizer_system_prompt.strip(),
                user_prompt=prompt,
                model=self._config.fast_llm_model,
            ):
                raw_buffer += chunk
                if remove_thinking:
                    for segment in flush_visible():
                        visible_output += segment
                        if segment:
                            yield segment
                else:
                    visible_output += chunk
                    if chunk:
                        yield chunk

            if remove_thinking:
                for segment in flush_visible():
                    visible_output += segment
                    if segment:
                        yield segment

        def get_summary() -> str:
            return strip_tool_calls(visible_output).strip()

        return generator(), get_summary

    def _build_prompt(self, state: SummaryState, task: TodoItem, context: str) -> str:
        """构建两种模式共享的总结提示。"""
        return (
            f"任务主题：{state.research_topic}\n"
            f"任务名称：{task.title}\n"
            f"任务目标：{task.intent}\n"
            f"检索查询：{task.query}\n"
            f"任务上下文：\n{context}\n"
            f"{build_note_guidance(task)}\n"
            "请按照以上协作要求先同步笔记，然后返回一份面向用户的 Markdown 总结（仍遵循任务总结模板）。"
        )
