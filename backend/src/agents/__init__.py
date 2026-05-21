"""多智能体抽象层 — 将服务层封装为正式的 Agent 接口。"""

from agents.base import AgentResult, BaseAgent
from agents.critic import CriticAgent
from agents.director import DirectorAgent
from agents.planner import PlannerAgent
from agents.researcher import ResearcherAgent
from agents.writer import WriterAgent

__all__ = [
    "AgentResult",
    "BaseAgent",
    "CriticAgent",
    "DirectorAgent",
    "PlannerAgent",
    "ResearcherAgent",
    "WriterAgent",
]
