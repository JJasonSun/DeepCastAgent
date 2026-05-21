"""Agent 抽象基类 — 定义所有 Agent 的统一接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentResult:
    """Agent 执行结果的统一包装。"""

    success: bool
    data: Any = None
    events: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    """所有 Agent 的抽象基类。

    每个 Agent 封装一个特定职责（规划、研究、评估、生成等），
    通过统一的 execute 接口接收上下文并返回结果。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 唯一名称（用于 Director 路由）。"""

    @property
    def capabilities(self) -> list[str]:
        """Agent 能力标签（用于 Director 决策和日志）。"""
        return []

    @abstractmethod
    def execute(self, context: dict[str, Any]) -> AgentResult:
        """执行核心任务。

        Args:
            context: 包含任务所需的所有输入。
                通用 key：state, config, client, emit_fn, cancel_event
                任务特定 key 由各 Agent 子类定义。

        Returns:
            AgentResult 统一结果包装。
        """
