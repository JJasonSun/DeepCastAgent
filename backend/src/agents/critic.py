"""评估 Agent — 封装报告质量评估和改进建议。"""

from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent
from services.reporter import ReportingService


class CriticAgent(BaseAgent):
    """负责评估报告质量并提出具体改进建议。

    能力：
    - critique: 评估报告的逻辑性、数据支撑度、专业性等维度
    """

    def __init__(self, service: ReportingService) -> None:
        self._service = service

    @property
    def name(self) -> str:
        return "critic"

    @property
    def capabilities(self) -> list[str]:
        return ["critique"]

    def execute(self, context: dict[str, Any]) -> AgentResult:
        report: str = context["report"]

        if not report:
            return AgentResult(success=False, data={"error": "No report to critique"})

        critique = self._service._critique_report(report)

        if not critique:
            return AgentResult(success=False, data={"error": "Critique failed"})

        return AgentResult(
            success=True,
            data={
                "overall_score": critique.get("overall_score", 0),
                "verdict": critique.get("verdict", "needs_revision"),
                "issues": critique.get("issues", []),
                "strengths": critique.get("strengths", []),
            },
            metrics={"score": critique.get("overall_score", 0)},
        )
