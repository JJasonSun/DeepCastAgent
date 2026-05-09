"""负责将研究主题转换为可操作任务的服务。"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from config import Configuration
from models import SummaryState, TodoItem
from prompts import get_current_date, todo_planner_instructions, todo_planner_system_prompt
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


class PlanningService:
    """使用 OpenAI SDK 结构化输出生成 TODO 项目。"""

    def __init__(self, client: OpenAI, config: Configuration) -> None:
        self._client = client
        self._config = config

    def plan_todo_list(self, state: SummaryState) -> list[TodoItem]:
        """要求规划器将主题分解为可操作的任务。"""
        prompt = todo_planner_instructions.format(
            current_date=get_current_date(),
            research_topic=state.research_topic,
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
