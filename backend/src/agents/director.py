"""导演 Agent — 协调各专业 Agent 的执行流程。"""

from __future__ import annotations

import logging
from typing import Any

from agents.base import AgentResult, BaseAgent

logger = logging.getLogger(__name__)


class DirectorAgent:
    """协调各专业 Agent 的执行流程。

    职责：
    1. 管理 Agent 注册表
    2. 根据当前状态决定下一步调用哪个 Agent
    3. 处理 Agent 之间的数据传递
    4. 实现智能终止策略
    """

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        """注册一个 Agent。"""
        self._agents[agent.name] = agent
        logger.debug("Registered agent: %s (capabilities: %s)", agent.name, agent.capabilities)

    def get_agent(self, name: str) -> BaseAgent | None:
        """按名称获取 Agent。"""
        return self._agents.get(name)

    @property
    def registered_agents(self) -> list[str]:
        """返回所有已注册 Agent 的名称列表。"""
        return list(self._agents.keys())

    def dispatch(self, agent_name: str, context: dict[str, Any]) -> AgentResult:
        """分派任务给指定 Agent。

        Args:
            agent_name: 目标 Agent 名称。
            context: 任务上下文。

        Returns:
            AgentResult 执行结果。

        Raises:
            KeyError: 如果 Agent 未注册。
        """
        agent = self._agents.get(agent_name)
        if agent is None:
            return AgentResult(
                success=False,
                data={"error": f"Agent '{agent_name}' not registered"},
            )

        logger.debug("Dispatching to agent '%s'", agent_name)
        result = agent.execute(context)

        if not result.success:
            logger.warning("Agent '%s' failed: %s", agent_name, result.data)
        else:
            logger.debug("Agent '%s' completed (metrics: %s)", agent_name, result.metrics)

        return result
