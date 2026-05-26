"""混合记忆管理器 — 研究发现的持久化与检索。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import Configuration
from models import SummaryState
from prompts import memory_extraction_instructions
from services.llm import call_llm_json

logger = logging.getLogger(__name__)

# 记忆提取输出的 JSON Schema
MEMORY_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": "研究主题的简洁概括",
        },
        "key_findings": {
            "type": "array",
            "items": {"type": "string"},
            "description": "3-7 条最重要的研究发现",
        },
        "entities": {
            "type": "array",
            "items": {"type": "string"},
            "description": "关键实体（公司、技术、人物、概念等）",
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "5-10 个相关关键词，用于未来检索",
        },
    },
    "required": ["topic", "key_findings", "entities", "keywords"],
}


class MemoryManager:
    """管理研究记忆的持久化与检索。

    记忆类型：
    - 长期记忆：每次研究完成后提取的关键发现，持久化到 JSON 文件
    - 检索机制：基于关键词匹配，找到与当前主题相关的历史发现
    """

    def __init__(self, config: Configuration, client: OpenAI | None = None) -> None:
        self._config = config
        self._client = client
        self._memory_dir = Path(config.notes_workspace).parent / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._memory_dir / "memory_index.json"
        self._load_index()

    def _load_index(self) -> None:
        """加载记忆索引。"""
        if self._index_file.exists():
            try:
                with open(self._index_file, encoding="utf-8") as f:
                    self._index: dict[str, Any] = json.load(f)
            except (json.JSONDecodeError, OSError):
                logger.warning("Failed to load memory index, creating new one")
                self._index = {"memories": [], "total": 0}
        else:
            self._index = {"memories": [], "total": 0}

    def _save_index(self) -> None:
        """保存记忆索引。"""
        try:
            with open(self._index_file, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Failed to save memory index: %s", e)

    def _get_memory_path(self, memory_id: str) -> Path:
        return self._memory_dir / f"{memory_id}.json"

    def save_research_memory(self, state: SummaryState) -> str | None:
        """从研究状态中提取关键发现并保存为长期记忆。

        Args:
            state: 完成研究后的状态对象。

        Returns:
            保存的记忆 ID，失败返回 None。
        """
        if not state.structured_report or not state.todo_items:
            return None

        # 汇总所有任务总结
        summaries = []
        for task in state.todo_items:
            if task.summary and task.status == "completed":
                summaries.append(f"【{task.title}】\n{task.summary}")

        if not summaries:
            return None

        combined_summary = "\n\n".join(summaries)

        # 使用 LLM 提取结构化记忆
        memory_data = self._extract_memory(state.research_topic or "", combined_summary)

        if not memory_data:
            return None

        # 生成记忆 ID 并保存
        memory_id = f"mem_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        memory_entry = {
            "id": memory_id,
            "topic": state.research_topic,
            "created_at": datetime.now().isoformat(),
            "summary": memory_data.get("topic", ""),
            "key_findings": memory_data.get("key_findings", []),
            "entities": memory_data.get("entities", []),
            "keywords": memory_data.get("keywords", []),
            "task_count": len(state.todo_items),
            "report_length": len(state.structured_report),
        }

        # 保存记忆文件
        memory_path = self._get_memory_path(memory_id)
        try:
            with open(memory_path, "w", encoding="utf-8") as f:
                json.dump(memory_entry, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error("Failed to save memory %s: %s", memory_id, e)
            return None

        # 更新索引
        self._index["memories"].append({
            "id": memory_id,
            "topic": state.research_topic,
            "keywords": memory_data.get("keywords", []),
            "created_at": memory_entry["created_at"],
        })
        self._index["total"] = len(self._index["memories"])
        self._save_index()

        logger.info(
            "Saved research memory %s: topic=%s, findings=%d, entities=%d",
            memory_id, state.research_topic,
            len(memory_data.get("key_findings", [])),
            len(memory_data.get("entities", [])),
        )
        return memory_id

    def retrieve_relevant_memories(
        self,
        topic: str,
        max_results: int = 3,
    ) -> list[dict[str, Any]]:
        """检索与当前主题相关的历史记忆。

        基于关键词匹配度排序，返回最相关的记忆条目。

        Args:
            topic: 当前研究主题。
            max_results: 最多返回的记忆条数。

        Returns:
            相关记忆列表，按相关度降序。
        """
        if not self._index.get("memories"):
            return []

        # 提取主题关键词（简单分词）
        topic_words = set(self._tokenize(topic))
        if not topic_words:
            return []

        # 计算每个记忆的相关度分数
        scored: list[tuple[float, dict[str, Any]]] = []
        for mem_ref in self._index["memories"]:
            keywords = set(mem_ref.get("keywords", []))
            # 也从 topic 中提取关键词
            mem_topic_words = set(self._tokenize(mem_ref.get("topic", "")))
            all_words = keywords | mem_topic_words

            if not all_words:
                continue

            # 计算交集比例（Jaccard 相似度的简化版）
            overlap = topic_words & all_words
            if not overlap:
                continue

            score = len(overlap) / max(len(topic_words), 1)
            scored.append((score, mem_ref))

        # 按分数降序排列
        scored.sort(key=lambda x: x[0], reverse=True)

        # 加载最相关的记忆详情
        results = []
        for score, mem_ref in scored[:max_results]:
            memory_path = self._get_memory_path(mem_ref["id"])
            if memory_path.exists():
                try:
                    with open(memory_path, encoding="utf-8") as f:
                        memory = json.load(f)
                    memory["relevance_score"] = round(score, 2)
                    results.append(memory)
                except (json.JSONDecodeError, OSError):
                    continue

        if results:
            logger.info(
                "Retrieved %d relevant memories for topic '%s' (top score: %.2f)",
                len(results), topic, results[0].get("relevance_score", 0),
            )

        return results

    def format_memories_for_context(self, memories: list[dict[str, Any]]) -> str:
        """将记忆列表格式化为可注入 prompt 的文本。"""
        if not memories:
            return ""

        parts = ["## 历史研究记忆（相关主题的已有发现）\n"]
        for i, mem in enumerate(memories, 1):
            topic = mem.get("topic", "未知主题")
            findings = mem.get("key_findings", [])
            entities = mem.get("entities", [])
            score = mem.get("relevance_score", 0)

            parts.append(f"### 记忆 {i}: {topic}（相关度 {score}）")
            if findings:
                parts.append("关键发现：")
                for finding in findings:
                    parts.append(f"- {finding}")
            if entities:
                parts.append(f"涉及实体：{', '.join(entities[:10])}")
            parts.append("")

        return "\n".join(parts)

    def _extract_memory(self, topic: str, summary: str) -> dict[str, Any] | None:
        """使用 LLM 从研究总结中提取结构化记忆。"""
        if not self._client:
            # 无 LLM 客户端时，使用简单的关键词提取
            return self._extract_memory_simple(topic, summary)

        prompt = memory_extraction_instructions.format(
            research_topic=topic,
            research_summary=summary[:3000],  # 限制长度避免 token 过多
        )
        extra_body = self._config.build_thinking_body(enable=False)

        result = call_llm_json(
            client=self._client,
            system_prompt="你是一名信息提取专家。",
            user_prompt=prompt,
            model=self._config.active_llm_model(),
            json_schema=MEMORY_EXTRACTION_SCHEMA,
            schema_name="memory_extraction",
            extra_body=extra_body,
            max_retries=self._config.llm_max_retries,
            retry_base_delay=self._config.llm_retry_base_delay,
        )

        if isinstance(result, dict):
            return result

        logger.warning("LLM memory extraction failed, falling back to simple extraction")
        return self._extract_memory_simple(topic, summary)

    @staticmethod
    def _extract_memory_simple(topic: str, summary: str) -> dict[str, Any]:
        """简单的关键词提取（不依赖 LLM）。"""
        # 提取列表项作为发现
        findings = []
        for line in summary.splitlines():
            line = line.strip()
            if line.startswith(("- ", "* ", "+ ")):
                finding = line[2:].strip().replace("**", "")
                if finding and len(finding) > 10:
                    findings.append(finding[:150])
                    if len(findings) >= 5:
                        break

        # 简单分词提取关键词
        keywords = MemoryManager._tokenize(topic)

        return {
            "topic": topic,
            "key_findings": findings,
            "entities": [],
            "keywords": keywords[:10],
        }

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单的中英文分词（基于标点和空格）。"""
        import re
        # 移除标点，按空格和中文字符边界分词
        text = re.sub(r'[　-〿＀-￯‘’“”\s\-_/\\]', ' ', text)
        words = []
        for segment in text.split():
            # 英文单词
            if segment.isascii():
                if len(segment) > 1:
                    words.append(segment.lower())
            else:
                # 中文：按 2-4 字滑动窗口
                for size in (2, 3, 4):
                    for i in range(len(segment) - size + 1):
                        words.append(segment[i:i + size])
        return words
