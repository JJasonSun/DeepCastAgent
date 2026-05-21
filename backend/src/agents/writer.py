"""生成 Agent — 封装报告撰写和脚本生成。"""

from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent
from models import SummaryState
from services.reporter import ReportingService
from services.script_generator import ScriptGenerationService


class WriterAgent(BaseAgent):
    """负责报告撰写和播客脚本生成。

    能力：
    - report: 生成结构化 Markdown 报告
    - report_with_refine: 生成报告并通过 Self-Refine 精炼
    - revise: 根据 Critic 反馈修改报告
    - script: 生成播客对话脚本
    """

    def __init__(
        self,
        reporter: ReportingService,
        script_generator: ScriptGenerationService,
    ) -> None:
        self._reporter = reporter
        self._script_generator = script_generator

    @property
    def name(self) -> str:
        return "writer"

    @property
    def capabilities(self) -> list[str]:
        return ["report", "revise", "script"]

    def execute(self, context: dict[str, Any]) -> AgentResult:
        action = context.get("action", "report")
        state: SummaryState = context["state"]

        if action == "report":
            return self._generate_report(context, state)
        elif action == "report_with_refine":
            return self._generate_report_with_refine(context, state)
        elif action == "revise":
            return self._revise_report(context)
        elif action == "script":
            return self._generate_script(context, state)
        else:
            return AgentResult(success=False, data={"error": f"Unknown action: {action}"})

    def _generate_report(self, context: dict[str, Any], state: SummaryState) -> AgentResult:
        report = self._reporter.generate_report(state)
        return AgentResult(
            success=bool(report),
            data={"report": report},
            metrics={"report_length": len(report) if report else 0},
        )

    def _generate_report_with_refine(self, context: dict[str, Any], state: SummaryState) -> AgentResult:
        report = self._reporter.generate_report_with_refine(state)
        return AgentResult(
            success=bool(report),
            data={"report": report},
            metrics={"report_length": len(report) if report else 0},
        )

    def _revise_report(self, context: dict[str, Any]) -> AgentResult:
        report: str = context["report"]
        critique: dict = context["critique"]
        revised = self._reporter._refine_report(report, critique)
        return AgentResult(
            success=bool(revised),
            data={"report": revised or report},
            metrics={"revised_length": len(revised) if revised else 0},
        )

    def _generate_script(self, context: dict[str, Any], state: SummaryState) -> AgentResult:
        script = self._script_generator.generate_script(state)
        return AgentResult(
            success=bool(script),
            data={"script": script},
            metrics={"turn_count": len(script) if script else 0},
        )
