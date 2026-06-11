"""将任务结果整合为最终报告的服务。"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from config import Configuration
from models import SummaryState
from prompts import (
    report_critic_instructions,
    report_outline_instructions,
    report_writer_instructions,
)
from services.llm import call_llm, call_llm_json
from services.text_processing import strip_tool_calls
from utils import strip_thinking_tokens

logger = logging.getLogger(__name__)
REPORT_GENERATION_FAILURE_MESSAGE = "报告生成失败，请检查输入。"


def is_report_generation_failure(report: str | None) -> bool:
    """判断文本是否是报告生成失败占位，而非真实研究报告。"""
    if not report or not report.strip():
        return True
    normalized = report.strip()
    if normalized == REPORT_GENERATION_FAILURE_MESSAGE:
        return True
    head = normalized[:800]
    return (
        "关于“AI 报告生成失败”的分析与改进报告" in head
        or "关于\"AI 报告生成失败\"的分析与改进报告" in head
        or "原报告生成任务因输入信息缺失或指令冲突" in head
    )

# 报告大纲与审稿输出的 JSON Schema
REPORT_OUTLINE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "报告标题",
        },
        "reader_question": {
            "type": "string",
            "description": "报告主要回答的读者问题",
        },
        "thesis": {
            "type": "string",
            "description": "核心判断或主线观点",
        },
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {
                        "type": "string",
                        "description": "章节标题",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "本章作用",
                    },
                    "key_claims": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "关键论点",
                    },
                    "evidence_needed": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要引用的证据、数据或案例",
                    },
                    "table_suggestion": {
                        "type": "string",
                        "description": "适合使用的表格或对比方式",
                    },
                },
                "required": [
                    "heading",
                    "purpose",
                    "key_claims",
                    "evidence_needed",
                    "table_suggestion",
                ],
            },
            "minItems": 3,
            "maxItems": 7,
        },
        "source_risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "证据不足、来源偏单一或需要谨慎表述的地方",
        },
    },
    "required": ["title", "reader_question", "thesis", "sections", "source_risks"],
}


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

    def generate_report(self, state: SummaryState, outline: dict[str, Any] | None = None) -> str:
        """
        基于完成的任务生成结构化报告。

        Args:
            state: 包含任务结果和笔记的研究状态。
            outline: 可选的已确认报告大纲，用于约束正式报告结构。

        Returns:
            Markdown 格式的报告文本。
        """
        tasks_context = self._build_tasks_context(state)
        if outline is None:
            outline = self._generate_report_outline(state, tasks_context)
        outline_block = ""
        if outline:
            outline_block = (
                "<REPORT_OUTLINE>\n"
                f"{self._format_outline(outline)}\n"
                "</REPORT_OUTLINE>\n\n"
            )

        prompt = (
            f"研究主题：{state.research_topic}\n"
            f"{outline_block}"
            f"<TASK_CONTEXT>\n{tasks_context}\n</TASK_CONTEXT>\n"
            "请整合所有任务的研究发现，撰写一份结构化的深度研究报告。"
            "报告必须围绕核心问题展开，保留证据线索，避免无来源的强结论。"
        )
        extra_body = self._config.build_thinking_body(enable=True)
        reasoning_effort = self._config.build_reasoning_effort(enable=True)

        response = call_llm(
            client=self._client,
            system_prompt=report_writer_instructions.strip(),
            user_prompt=prompt,
            model=self._config.active_llm_model(),
            extra_body=extra_body,
            reasoning_effort=reasoning_effort,
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
            timeout=self._config.llm_long_timeout,
        )

        report_text = response.strip()
        if self._config.strip_thinking_tokens:
            report_text = strip_thinking_tokens(report_text)

        report_text = strip_tool_calls(report_text).strip()

        if not report_text:
            logger.error("Report generation returned empty text.")
        return report_text

    def generate_report_outline(self, state: SummaryState) -> dict[str, Any] | None:
        """生成可供用户确认的报告大纲。"""
        tasks_context = self._build_tasks_context(state)
        return self._generate_report_outline(state, tasks_context)

    def _build_tasks_context(self, state: SummaryState) -> str:
        """构建报告写作所需的任务上下文。"""
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
        return "\n".join(tasks_block)

    def _generate_report_outline(
        self,
        state: SummaryState,
        tasks_context: str,
    ) -> dict[str, Any] | None:
        """先生成报告大纲，用于约束正式报告的结构、证据和主线。"""
        if not self._config.enable_report_outline:
            return None

        prompt = (
            f"研究主题：{state.research_topic}\n\n"
            f"<TASK_CONTEXT>\n{tasks_context}\n</TASK_CONTEXT>"
        )
        extra_body = self._config.build_thinking_body(enable=True)
        reasoning_effort = self._config.build_reasoning_effort(enable=True)

        result = call_llm_json(
            client=self._client,
            system_prompt=report_outline_instructions.strip(),
            user_prompt=prompt,
            model=self._config.active_llm_model(),
            json_schema=REPORT_OUTLINE_JSON_SCHEMA,
            schema_name="report_outline",
            extra_body=extra_body,
            reasoning_effort=reasoning_effort,
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
            timeout=self._config.llm_long_timeout,
        )

        if isinstance(result, dict):
            logger.info("Generated report outline: %s", result.get("title", "untitled"))
            return result
        logger.warning("Report outline generation returned no result; falling back to direct report generation")
        return None

    @staticmethod
    def _format_outline(outline: dict[str, Any]) -> str:
        """将结构化大纲格式化为可读上下文。"""
        lines = [
            f"标题：{outline.get('title', '')}",
            f"读者问题：{outline.get('reader_question', '')}",
            f"核心主线：{outline.get('thesis', '')}",
            "",
            "章节规划：",
        ]
        for idx, section in enumerate(outline.get("sections", []), 1):
            if not isinstance(section, dict):
                continue
            key_claims = "；".join(section.get("key_claims", []) or [])
            evidence = "；".join(section.get("evidence_needed", []) or [])
            lines.extend([
                f"{idx}. {section.get('heading', '')}",
                f"   作用：{section.get('purpose', '')}",
                f"   关键论点：{key_claims}",
                f"   证据需求：{evidence}",
                f"   表格建议：{section.get('table_suggestion', '')}",
            ])
        source_risks = outline.get("source_risks", [])
        if source_risks:
            lines.append("")
            lines.append("来源风险：" + "；".join(str(risk) for risk in source_risks))
        return "\n".join(lines)

    def generate_report_with_refine(self, state: SummaryState) -> str:
        """生成报告并通过批判-修改循环精炼质量。"""
        # Step 1: 生成初稿
        draft = self.generate_report(state)
        if is_report_generation_failure(draft):
            logger.error("Report draft is empty or failure placeholder; skipping refinement.")
            return ""

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
            if revised and not is_report_generation_failure(revised):
                current_report = revised
            else:
                logger.warning("Report refinement returned empty or failure placeholder, keeping previous version")
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
        if is_report_generation_failure(draft):
            events.append({"type": "log", "message": "报告初稿生成失败，停止报告精炼"})
            return "", events
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
            if revised and not is_report_generation_failure(revised):
                current_report = revised
                events.append({
                    "type": "log",
                    "message": f"报告修改完成，当前 {len(current_report)} 字符",
                })
            else:
                events.append({"type": "log", "message": "报告修改返回空或失败占位，保留上一版本"})
                break

        return current_report, events

    def _critique_report(self, report: str) -> dict[str, Any] | None:
        """使用 Critic Agent 评估报告质量。"""
        prompt = (
            f"请评估以下研究报告的质量：\n\n"
            f"{'=' * 40}\n{report}\n{'=' * 40}"
        )
        extra_body = self._config.build_thinking_body(enable=True)
        reasoning_effort = self._config.build_reasoning_effort(enable=True)

        result = call_llm_json(
            client=self._client,
            system_prompt=report_critic_instructions.strip(),
            user_prompt=prompt,
            model=self._config.active_llm_model(),
            json_schema=CRITIC_JSON_SCHEMA,
            schema_name="report_critique",
            extra_body=extra_body,
            reasoning_effort=reasoning_effort,
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
            timeout=self._config.llm_long_timeout,
        )

        if isinstance(result, dict):
            return result
        return None

    def _refine_report(self, report: str, critique: dict[str, Any]) -> str:
        """根据审稿意见修改报告。"""
        if is_report_generation_failure(report):
            logger.error("Refusing to refine invalid report placeholder.")
            return ""

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
        extra_body = self._config.build_thinking_body(enable=True)
        reasoning_effort = self._config.build_reasoning_effort(enable=True)

        response = call_llm(
            client=self._client,
            system_prompt=report_writer_instructions.strip(),
            user_prompt=prompt,
            model=self._config.active_llm_model(),
            extra_body=extra_body,
            reasoning_effort=reasoning_effort,
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
            timeout=self._config.llm_long_timeout,
        )

        refined_text = response.strip()
        if self._config.strip_thinking_tokens:
            refined_text = strip_thinking_tokens(refined_text)

        refined_text = strip_tool_calls(refined_text).strip()

        return refined_text or report
