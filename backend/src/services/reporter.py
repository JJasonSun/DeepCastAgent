"""将任务结果整合为最终报告的服务。"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from config import Configuration
from models import SummaryState
from prompts import report_critic_instructions, report_writer_instructions
from services.llm import call_llm, call_llm_json
from services.text_processing import strip_tool_calls
from utils import strip_thinking_tokens

logger = logging.getLogger(__name__)

# 报告审稿输出的 JSON Schema
CRITIC_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_score": {
            "type": "integer",
            "description": "报告整体评分（1-10）",
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "dimension": {
                        "type": "string",
                        "description": "评估维度",
                    },
                    "description": {
                        "type": "string",
                        "description": "具体问题描述",
                    },
                    "suggestion": {
                        "type": "string",
                        "description": "改进建议",
                    },
                },
                "required": ["dimension", "description", "suggestion"],
            },
        },
        "strengths": {
            "type": "array",
            "items": {"type": "string"},
        },
        "verdict": {
            "type": "string",
            "enum": ["pass", "needs_revision"],
        },
    },
    "required": ["overall_score", "issues", "strengths", "verdict"],
}


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

    def generate_report_with_refine(self, state: SummaryState) -> str:
        """生成报告并通过批判-修改循环精炼质量。"""
        # Step 1: 生成初稿
        draft = self.generate_report(state)

        if self._config.max_report_refine_rounds <= 0:
            return draft

        # Step 2: 迭代精炼
        current_report = draft
        for round_num in range(self._config.max_report_refine_rounds):
            # 2a: Critic 评估
            critique = self._critique_report(current_report)
            if not critique:
                logger.warning("Report critique returned no result, stopping refinement")
                break

            verdict = critique.get("verdict", "pass")
            score = critique.get("overall_score", 0)
            logger.info(
                "Report critique round %d: score=%d/10, verdict=%s",
                round_num + 1, score, verdict,
            )

            if verdict == "pass":
                break

            # 2b: Writer 修改
            revised = self._refine_report(current_report, critique)
            if revised:
                current_report = revised
            else:
                logger.warning("Report refinement returned empty, keeping previous version")
                break

        return current_report

    def generate_report_with_refine_stream(
        self,
        state: SummaryState,
    ) -> tuple[str, list[dict[str, Any]]]:
        """生成报告并精炼，同时收集进度事件。

        Returns:
            (最终报告, 事件列表)
        """
        events: list[dict[str, Any]] = []

        # Step 1: 生成初稿
        draft = self.generate_report(state)
        events.append({"type": "log", "message": f"报告初稿生成完成，共 {len(draft)} 字符"})

        if self._config.max_report_refine_rounds <= 0:
            return draft, events

        # Step 2: 迭代精炼
        current_report = draft
        for round_num in range(self._config.max_report_refine_rounds):
            events.append({
                "type": "report_refine",
                "round": round_num + 1,
                "max_rounds": self._config.max_report_refine_rounds,
                "phase": "critique",
                "message": f"正在评估报告质量（第 {round_num + 1} 轮）...",
            })

            critique = self._critique_report(current_report)
            if not critique:
                events.append({"type": "log", "message": "报告评估返回空结果，停止精炼"})
                break

            verdict = critique.get("verdict", "pass")
            score = critique.get("overall_score", 0)
            issues = critique.get("issues", [])

            events.append({
                "type": "report_refine",
                "round": round_num + 1,
                "max_rounds": self._config.max_report_refine_rounds,
                "phase": "result",
                "score": score,
                "verdict": verdict,
                "issue_count": len(issues),
                "message": f"报告评分 {score}/10，发现 {len(issues)} 个问题，判定: {verdict}",
            })

            if verdict == "pass":
                events.append({"type": "log", "message": f"报告质量达标（{score}/10），无需修改"})
                break

            events.append({
                "type": "log",
                "message": f"根据审稿意见修改报告（{len(issues)} 个问题）...",
            })

            revised = self._refine_report(current_report, critique)
            if revised:
                current_report = revised
                events.append({
                    "type": "log",
                    "message": f"报告修改完成，当前 {len(current_report)} 字符",
                })
            else:
                events.append({"type": "log", "message": "报告修改返回空，保留上一版本"})
                break

        return current_report, events

    def _critique_report(self, report: str) -> dict[str, Any] | None:
        """使用 Critic Agent 评估报告质量。"""
        prompt = (
            f"请评估以下研究报告的质量：\n\n"
            f"{'=' * 40}\n{report}\n{'=' * 40}"
        )

        result = call_llm_json(
            client=self._client,
            system_prompt=report_critic_instructions.strip(),
            user_prompt=prompt,
            model=self._config.smart_llm_model,
            json_schema=CRITIC_JSON_SCHEMA,
            schema_name="report_critique",
        )

        if isinstance(result, dict):
            return result
        return None

    def _refine_report(self, report: str, critique: dict[str, Any]) -> str:
        """根据审稿意见修改报告。"""
        issues = critique.get("issues", [])
        if not issues:
            return report

        # 构建修改指令
        issues_text = []
        for i, issue in enumerate(issues, 1):
            dim = issue.get("dimension", "")
            desc = issue.get("description", "")
            suggestion = issue.get("suggestion", "")
            issues_text.append(f"{i}. [{dim}] {desc}\n   建议：{suggestion}")

        prompt = (
            "请根据以下审稿意见修改报告。只修改有问题的部分，保持报告的整体结构和已有的优点。\n\n"
            "## 审稿意见\n"
            f"整体评分：{critique.get('overall_score', 'N/A')}/10\n"
            f"优点：{', '.join(critique.get('strengths', []))}\n\n"
            "### 需要改进的问题：\n"
            + "\n".join(issues_text)
            + "\n\n"
            "## 原报告\n"
            f"{report}\n\n"
            "请输出修改后的完整报告（Markdown 格式），不要输出其他内容。"
        )

        response = call_llm(
            client=self._client,
            system_prompt=report_writer_instructions.strip(),
            user_prompt=prompt,
            model=self._config.smart_llm_model,
        )

        refined_text = response.strip()
        if self._config.strip_thinking_tokens:
            refined_text = strip_thinking_tokens(refined_text)

        refined_text = strip_tool_calls(refined_text).strip()

        return refined_text or report
