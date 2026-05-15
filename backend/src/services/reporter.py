"""将任务结果整合为最终报告的服务。"""

from __future__ import annotations

from openai import OpenAI

from config import Configuration
from models import SummaryState
from prompts import report_writer_instructions
from services.llm import call_llm
from services.text_processing import strip_tool_calls
from utils import strip_thinking_tokens


class ReportingService:
    """生成最终的结构化报告。"""

    def __init__(self, client: OpenAI, config: Configuration) -> None:
        self._client = client
        self._config = config

    def generate_report(self, state: SummaryState) -> str:
        """
        基于完成的任务生成结构化报告。

        Args:
            state: 包含任务结果和笔记的研究状态。

        Returns:
            Markdown 格式的报告文本。
        """
        tasks_block = []
        for task in state.todo_items:
            summary_block = task.summary or "暂无可用信息"
            sources_block = task.sources_summary or "暂无来源"
            tasks_block.append(
                f"### 任务 {task.id}: {task.title}\n"
                f"- 任务目标：{task.intent}\n"
                f"- 检索查询：{task.query}\n"
                f"- 执行状态：{task.status}\n"
                f"- 任务总结：\n{summary_block}\n"
                f"- 来源概览：\n{sources_block}\n"
            )

        prompt = (
            f"研究主题：{state.research_topic}\n"
            f"任务概览：\n{''.join(tasks_block)}\n"
            "请整合所有任务的研究发现，撰写一份结构化的深度研究报告。"
            "报告应包含：摘要、各主题的详细分析、关键发现、结论与展望。"
        )

        response = call_llm(
            client=self._client,
            system_prompt=report_writer_instructions.strip(),
            user_prompt=prompt,
            model=self._config.smart_llm_model,
        )

        report_text = response.strip()
        if self._config.strip_thinking_tokens:
            report_text = strip_thinking_tokens(report_text)

        report_text = strip_tool_calls(report_text).strip()

        return report_text or "报告生成失败，请检查输入。"
