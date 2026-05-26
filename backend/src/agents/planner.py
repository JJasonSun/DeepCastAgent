"""规划 Agent — 封装 PlanningService 的任务分解与信息增益分析。"""

from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent
from models import SummaryState
from services.planner import PlanningService


class PlannerAgent(BaseAgent):
    """负责将研究主题拆解为可执行任务，并分析信息增益。

    能力：
    - plan: 将主题分解为 3-5 个 TodoItem 子任务
    - analyze: 分析已有信息，判断是否需要补充搜索
    - fallback: 生成兜底任务
    - gain: 计算信息增益比例
    """

    def __init__(self, service: PlanningService) -> None:
        self._service = service

    @property
    def name(self) -> str:
        return "planner"

    @property
    def capabilities(self) -> list[str]:
        return ["plan", "analyze", "fallback", "gain"]

    def execute(self, context: dict[str, Any]) -> AgentResult:
        action = context.get("action", "plan")
        state: SummaryState = context["state"]

        if action == "plan":
            return self._plan(context, state)
        elif action == "analyze":
            return self._analyze(context, state)
        elif action == "fallback":
            return self._fallback(context, state)
        elif action == "gain":
            return self._calculate_gain(context, state)
        else:
            return AgentResult(success=False, data={"error": f"Unknown action: {action}"})

    def _plan(self, context: dict[str, Any], state: SummaryState) -> AgentResult:
        historical_context = context.get("historical_context", "")
        tasks = self._service.plan_todo_list(state, historical_context)
        return AgentResult(
            success=bool(tasks),
            data={"tasks": tasks},
            metrics={"task_count": len(tasks)},
        )

    def _analyze(self, context: dict[str, Any], state: SummaryState) -> AgentResult:
        current_round = context.get("current_round", 0)
        max_rounds = context.get("max_rounds", 2)
        should_continue, reason, new_tasks = self._service.analyze_and_refine(
            state, current_round, max_rounds,
        )
        return AgentResult(
            success=True,
            data={
                "should_continue": should_continue,
                "reason": reason,
                "new_tasks": new_tasks,
            },
            metrics={"new_task_count": len(new_tasks)},
        )

    def _fallback(self, context: dict[str, Any], state: SummaryState) -> AgentResult:
        task = self._service.create_fallback_task(state)
        return AgentResult(
            success=True,
            data={"task": task},
            metrics={"task_count": 1},
        )

    def _calculate_gain(self, context: dict[str, Any], state: SummaryState) -> AgentResult:
        new_tasks = context.get("new_tasks", [])
        gain = self._service.calculate_information_gain(state, new_tasks)
        return AgentResult(
            success=True,
            data={"gain": gain},
            metrics={"information_gain": gain},
        )
