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

# 规划器输出的 JSON Schema（用于 DeepSeek JSON Output 提示与本地解析）
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
        "coverage_summary": {
            "type": "string",
            "description": "已有信息覆盖情况的简要总结",
        },
        "knowledge_gaps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "仍缺失或证据不足的信息",
        },
        "next_search_strategy": {
            "type": "string",
            "description": "下一轮搜索策略或终止理由",
        },
        "source_strategy": {
            "type": "string",
            "description": "应优先寻找的来源类型",
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
    "required": [
        "continue_search",
        "reason",
        "coverage_summary",
        "knowledge_gaps",
        "next_search_strategy",
        "source_strategy",
        "tasks",
    ],
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
        extra_body = self._config.build_thinking_body(enable=False)

        result = call_llm_json(
            client=self._client,
            system_prompt=todo_planner_system_prompt.strip(),
            user_prompt=prompt,
            model=self._config.active_llm_model(),
            json_schema=PLANNER_JSON_SCHEMA,
            schema_name="research_tasks",
            extra_body=extra_body,
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
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
        extra_body = self._config.build_thinking_body(enable=True)
        reasoning_effort = self._config.build_reasoning_effort(enable=True)

        result = call_llm_json(
            client=self._client,
            system_prompt=research_analyzer_system_prompt.strip(),
            user_prompt=prompt,
            model=self._config.active_llm_model(),
            json_schema=REFINE_JSON_SCHEMA,
            schema_name="refine_decision",
            extra_body=extra_body,
            reasoning_effort=reasoning_effort,
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
        )

        if not result or not isinstance(result, dict):
            logger.warning("Refine analysis returned no result, stopping")
            return False, "分析失败，停止精炼", []

        should_continue = bool(result.get("continue_search", False))
        reason = str(result.get("reason", ""))
        coverage_summary = str(result.get("coverage_summary", "")).strip()
        knowledge_gaps = result.get("knowledge_gaps", [])
        next_search_strategy = str(result.get("next_search_strategy", "")).strip()
        source_strategy = str(result.get("source_strategy", "")).strip()
        reflection_parts = [reason]
        if coverage_summary:
            reflection_parts.append(f"覆盖情况：{coverage_summary}")
        if isinstance(knowledge_gaps, list) and knowledge_gaps:
            gaps_text = "；".join(str(gap) for gap in knowledge_gaps if gap)
            if gaps_text:
                reflection_parts.append(f"信息缺口：{gaps_text}")
        if next_search_strategy:
            reflection_parts.append(f"搜索策略：{next_search_strategy}")
        if source_strategy:
            reflection_parts.append(f"来源策略：{source_strategy}")
        reason = "\n".join(part for part in reflection_parts if part)
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

    @staticmethod
    def calculate_information_gain(
        state: SummaryState,
        new_tasks: list[TodoItem],
    ) -> float:
        """计算本轮新增信息的增益比例（0-1）。

        基于新任务 summary 与已有信息的关键词重叠度。
        返回值越高表示重复越多（信息增益越低）。

        Args:
            state: 当前研究状态。
            new_tasks: 本轮新增的任务列表。

        Returns:
            信息重复度（0-1），1 表示完全重复，0 表示全新信息。
        """
        import re

        def _simple_tokenize(text: str) -> set[str]:
            """简单的中英文分词。"""
            text = re.sub(r'[^\w\s]', ' ', text)
            words = set()
            for segment in text.split():
                if segment.isascii():
                    if len(segment) > 1:
                        words.add(segment.lower())
                else:
                    for size in (2, 3, 4):
                        for i in range(len(segment) - size + 1):
                            words.add(segment[i:i + size])
            return words

        # 提取已有信息的关键词
        existing_texts = [
            t.summary for t in state.todo_items
            if t.summary and t.status == "completed" and t not in new_tasks
        ]
        existing_words = _simple_tokenize(" ".join(existing_texts))

        # 提取新信息的关键词
        new_texts = [t.summary for t in new_tasks if t.summary]
        new_words = _simple_tokenize(" ".join(new_texts))

        if not new_words:
            return 1.0  # 无新信息，视为完全重复

        overlap = len(existing_words & new_words)
        return overlap / max(len(new_words), 1)
