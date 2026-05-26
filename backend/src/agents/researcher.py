"""研究 Agent — 封装搜索、过滤、摘要的完整研究流程。"""

from __future__ import annotations

from typing import Any

from agents.base import AgentResult, BaseAgent
from config import Configuration
from models import SummaryState, TodoItem
from services.search import (
    dispatch_search,
    filter_search_results,
    prepare_research_context,
    sort_by_authority,
)
from services.summarizer import SummarizationService


class ResearcherAgent(BaseAgent):
    """负责执行单个研究任务：搜索 → 过滤 → 权威性排序 → 摘要。

    能力：
    - search: 执行搜索并返回结果
    - research: 完整研究流程（搜索 + 过滤 + 排序 + 摘要）
    """

    def __init__(
        self,
        summarizer: SummarizationService,
        config: Configuration,
        client: Any,
    ) -> None:
        self._summarizer = summarizer
        self._config = config
        self._client = client

    @property
    def name(self) -> str:
        return "researcher"

    @property
    def capabilities(self) -> list[str]:
        return ["search", "research", "filter"]

    def execute(self, context: dict[str, Any]) -> AgentResult:
        action = context.get("action", "research")
        state: SummaryState = context["state"]
        task: TodoItem = context["task"]

        if action == "search":
            return self._search(context, state, task)
        elif action == "research":
            return self._full_research(context, state, task)
        else:
            return AgentResult(success=False, data={"error": f"Unknown action: {action}"})

    def _search(
        self, context: dict[str, Any], state: SummaryState, task: TodoItem,
    ) -> AgentResult:
        """仅执行搜索，返回原始结果。"""
        search_result, notices, backend = dispatch_search(task.query, self._config)
        if not search_result or not search_result.get("results"):
            return AgentResult(success=False, data={"error": "No search results"})

        results = search_result["results"]

        # LLM 过滤
        if self._config.enable_search_filter:
            results = filter_search_results(
                results, state.research_topic or task.query, self._client, self._config,
            )

        # 权威性排序
        results = sort_by_authority(results)

        return AgentResult(
            success=True,
            data={"results": results, "backend": backend, "notices": notices},
            metrics={"result_count": len(results)},
        )

    def _full_research(
        self, context: dict[str, Any], state: SummaryState, task: TodoItem,
    ) -> AgentResult:
        """完整研究流程：搜索 → 过滤 → 排序 → 摘要。"""
        # 搜索
        search_result = self._search(context, state, task)
        if not search_result.success:
            return search_result

        results = search_result.data["results"]

        # 构建研究上下文
        search_payload = {"results": results, "backend": search_result.data.get("backend", "")}
        sources_summary, research_context = prepare_research_context(search_payload, self._config)

        # 摘要
        summary = self._summarizer.summarize_task(state, task, research_context)

        return AgentResult(
            success=bool(summary),
            data={
                "summary": summary,
                "sources_summary": sources_summary,
                "research_context": research_context,
            },
            metrics={
                "result_count": len(results),
                "summary_length": len(summary) if summary else 0,
            },
        )
