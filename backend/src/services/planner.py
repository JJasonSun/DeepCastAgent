"""负责将研究主题转换为可操作任务的服务。"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from config import Configuration
from models import SummaryState, TodoItem
from prompts import (
    get_current_date,
    research_analyzer_instructions,
    research_analyzer_system_prompt,
    todo_planner_instructions,
    todo_planner_system_prompt,
)
from services.llm import call_llm_json

logger = logging.getLogger(__name__)

# 规划器输出的 JSON Schema（用于 XGrammar 约束解码，保证 100% 结构正确）
PLANNER_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "简洁的任务名称（不超过10个字）",
                    },
                    "intent": {
                        "type": "string",
                        "description": "该任务要解答的核心问题（1-2句话）",
                    },
                    "query": {
                        "type": "string",
                        "description": "推荐的搜索关键词或查询语句",
                    },
                },
                "required": ["title", "intent", "query"],
            },
            "minItems": 3,
            "maxItems": 5,
        }
    },
    "required": ["tasks"],
}

# 深度搜索精炼输出的 JSON Schema
REFINE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "continue_search": {
            "type": "boolean",
            "description": "是否需要继续搜索",
        },
        "reason": {
            "type": "string",
            "description": "判断原因（信息缺口或饱和理由）",
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "补充任务名称",
                    },
                    "intent": {
                        "type": "string",
                        "description": "要填补的具体知识缺口",
                    },
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                },
                "required": ["title", "intent", "query"],
            },
            "maxItems": 3,
        },
    },
    "required": ["continue_search", "reason", "tasks"],
}


class PlanningService:
    """使用 OpenAI SDK 结构化输出生成 TODO 项目。"""

    def __init__(self, client: OpenAI, config: Configuration) -> None:
        self._client = client
        self._config = config

    def plan_todo_list(
        self,
        state: SummaryState,
        historical_context: str = "",
    ) -> list[TodoItem]:
        """要求规划器将主题分解为可操作的任务。

        Args:
            state: 研究状态。
            historical_context: 可选的历史研究记忆文本，注入规划 prompt。
        """
        prompt = todo_planner_instructions.format(
            current_date=get_current_date(),
            research_topic=state.research_topic,
            historical_context=historical_context,
        )

        result = call_llm_json(
            client=self._client,
            system_prompt=todo_planner_system_prompt.strip(),
            user_prompt=prompt,
            model=self._config.smart_llm_model,
            json_schema=PLANNER_JSON_SCHEMA,
            schema_name="research_tasks",
        )

        # 结构化输出保证 JSON 格式正确，直接提取 tasks 数组
        tasks_payload: list[dict[str, Any]] = []
        if isinstance(result, dict):
            candidate = result.get("tasks")
            if isinstance(candidate, list):
                tasks_payload = candidate
        elif isinstance(result, list):
            tasks_payload = result

        todo_items: list[TodoItem] = []
        for idx, item in enumerate(tasks_payload, start=1):
            title = str(item.get("title") or f"任务{idx}").strip()
            intent = str(item.get("intent") or "聚焦主题的关键问题").strip()
            query = str(item.get("query") or state.research_topic).strip()
            if not query:
                query = state.research_topic
            todo_items.append(TodoItem(id=idx, title=title, intent=intent, query=query))

        state.todo_items = todo_items
        logger.info("Planner produced %d tasks: %s", len(todo_items), [t.title for t in todo_items])
        return todo_items

    @staticmethod
    def create_fallback_task(state: SummaryState) -> TodoItem:
        """规划失败时创建一个最小的回退任务。"""
        return TodoItem(
            id=1,
            title="基础背景梳理",
            intent="收集主题的核心背景与最新动态",
            query=f"{state.research_topic} 最新进展" if state.research_topic else "基础背景梳理",
        )

    def analyze_and_refine(
        self,
        state: SummaryState,
        current_round: int,
        max_rounds: int,
    ) -> tuple[bool, str, list[TodoItem]]:
        """分析已有研究信息，判断是否需要补充搜索任务。

        Returns:
            (should_continue, reason, new_tasks)
        """
        # 汇总已有研究总结
        summaries = []
        for task in state.todo_items:
            if task.summary and task.status == "completed":
                summaries.append(f"【{task.title}】\n{task.summary}")
        existing_summaries = "\n\n".join(summaries) if summaries else "暂无研究总结"

        # 汇总历史搜索查询
        queries = [task.query for task in state.todo_items if task.query]
        previous_queries = "\n".join(f"- {q}" for q in queries) if queries else "（无）"

        prompt = research_analyzer_instructions.format(
            research_topic=state.research_topic,
            current_round=current_round + 1,
            max_rounds=max_rounds,
            existing_summaries=existing_summaries,
            previous_queries=previous_queries,
        )

        result = call_llm_json(
            client=self._client,
            system_prompt=research_analyzer_system_prompt.strip(),
            user_prompt=prompt,
            model=self._config.smart_llm_model,
            json_schema=REFINE_JSON_SCHEMA,
            schema_name="refine_decision",
        )

        if not result or not isinstance(result, dict):
            logger.warning("Refine analysis returned no result, stopping")
            return False, "分析失败，停止精炼", []

        should_continue = bool(result.get("continue_search", False))
        reason = str(result.get("reason", ""))
        tasks_payload = result.get("tasks", [])

        new_tasks: list[TodoItem] = []
        if should_continue and isinstance(tasks_payload, list):
            # 任务 ID 从现有任务数 + 1 开始
            start_id = len(state.todo_items) + 1
            for idx, item in enumerate(tasks_payload):
                title = str(item.get("title") or f"补充任务{idx + 1}").strip()
                intent = str(item.get("intent") or "补充研究信息").strip()
                query = str(item.get("query") or state.research_topic).strip()
                if not query:
                    query = state.research_topic
                new_tasks.append(TodoItem(id=start_id + idx, title=title, intent=intent, query=query))

        logger.info(
            "Refine analysis round %d: continue=%s, reason=%s, new_tasks=%d",
            current_round + 1, should_continue, reason, len(new_tasks),
        )

        return should_continue, reason, new_tasks
