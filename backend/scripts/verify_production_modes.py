"""验证快速/深度模式配置映射与报告大纲确认状态机。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from threading import Event, Lock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from agent import DeepResearchAgent
from config import Configuration
from main import ResearchRequest, _build_config
from models import SummaryState


def _fake_outline(title: str) -> dict:
    return {
        "title": title,
        "reader_question": "这件事为什么重要？",
        "thesis": "围绕关键变化、影响和风险展开。",
        "sections": [
            {
                "heading": "背景",
                "purpose": "交代事件背景",
                "key_claims": ["背景清楚"],
                "evidence_needed": ["官方来源"],
                "table_suggestion": "时间线",
            },
            {
                "heading": "影响",
                "purpose": "分析影响",
                "key_claims": ["影响明确"],
                "evidence_needed": ["案例"],
                "table_suggestion": "对比表",
            },
            {
                "heading": "风险",
                "purpose": "提示风险",
                "key_claims": ["风险可控"],
                "evidence_needed": ["多方观点"],
                "table_suggestion": "风险清单",
            },
        ],
        "source_risks": ["需要交叉验证"],
    }


class FakeReporting:
    """按顺序返回报告大纲。"""

    def __init__(self) -> None:
        self.calls = 0

    def generate_report_outline(self, state: SummaryState) -> dict:
        self.calls += 1
        return _fake_outline(f"大纲 {self.calls}")


def _build_agent() -> DeepResearchAgent:
    agent = object.__new__(DeepResearchAgent)
    agent.config = Configuration.from_env(
        {
            "production_mode": "deep",
            "enable_report_outline": True,
            "require_report_outline_confirmation": True,
            "report_outline_max_attempts": 3,
        }
    )
    agent.reporting = FakeReporting()
    agent._cancel_event = Event()
    agent._outline_action_event = Event()
    agent._outline_action_lock = Lock()
    agent._outline_action = None
    agent._waiting_for_outline_confirmation = False
    return agent


def _assert_config_mapping() -> None:
    quick = _build_config(
        ResearchRequest(
            topic="测试",
            search_depth="quick",
            podcast_duration="short",
            podcast_style="plain",
            enable_intro_bgm=False,
        )
    )
    assert quick.production_mode == "quick"
    assert quick.search_depth == "quick"
    assert quick.active_llm_model() == "deepseek-v4-flash"
    assert quick.llm_reasoning_effort == "high"
    assert quick.max_research_refine_rounds == 0
    assert quick.max_report_refine_rounds == 0
    assert quick.enable_report_outline is False
    assert quick.enable_script_blueprint is False
    assert quick.require_report_outline_confirmation is False
    assert quick.podcast_script_target_turns == "6-8"
    assert quick.podcast_style == "plain"
    assert quick.enable_intro_bgm is False

    standard = _build_config(
        ResearchRequest(
            topic="测试",
            search_depth="quick",
            podcast_duration="standard",
            podcast_style="professional",
        )
    )
    assert standard.podcast_script_target_turns == "12-14"
    assert standard.podcast_style == "professional"

    deep = _build_config(
        ResearchRequest(
            topic="测试",
            search_depth="deep",
            podcast_duration="deep",
            podcast_style="news",
            enable_intro_bgm=True,
        )
    )
    assert deep.production_mode == "deep"
    assert deep.search_depth == "deep"
    assert deep.active_llm_model() == "deepseek-v4-pro"
    assert deep.llm_reasoning_effort == "max"
    assert deep.max_research_refine_rounds == 2
    assert deep.max_report_refine_rounds == 1
    assert deep.enable_report_outline is True
    assert deep.enable_script_blueprint is True
    assert deep.require_report_outline_confirmation is True
    assert deep.podcast_script_target_turns == "16-20"
    assert deep.podcast_style == "news"
    assert deep.enable_intro_bgm is True

    legacy = _build_config(ResearchRequest(topic="测试", production_mode="quick"))
    assert legacy.search_depth == "quick"


def _assert_approve_flow() -> None:
    agent = _build_agent()
    state = SummaryState(research_topic="测试主题")
    stream = agent._stream_report_outline_review(state)

    assert next(stream)["type"] == "log"
    review = next(stream)
    assert review["type"] == "report_outline_review"
    assert review["attempt"] == 1
    assert agent.submit_report_outline_action("approve") is True
    assert next(stream)["type"] == "log"
    assert next(stream)["type"] == "log"
    try:
        next(stream)
    except StopIteration as exc:
        outline = exc.value
    else:
        raise AssertionError("确认大纲后应结束等待流程")
    assert outline["title"] == "大纲 1"
    assert agent.submit_report_outline_action("approve") is False


def _assert_regenerate_flow() -> None:
    agent = _build_agent()
    state = SummaryState(research_topic="测试主题")
    stream = agent._stream_report_outline_review(state)

    assert next(stream)["type"] == "log"
    first_review = next(stream)
    assert first_review["attempt"] == 1
    assert agent.submit_report_outline_action("regenerate") is True
    assert next(stream)["type"] == "log"
    assert next(stream)["type"] == "log"
    assert next(stream)["type"] == "log"
    second_review = next(stream)
    assert second_review["type"] == "report_outline_review"
    assert second_review["attempt"] == 2
    assert second_review["outline"]["title"] == "大纲 2"
    assert agent.submit_report_outline_action("approve") is True
    assert next(stream)["type"] == "log"
    assert next(stream)["type"] == "log"
    try:
        next(stream)
    except StopIteration as exc:
        outline = exc.value
    else:
        raise AssertionError("重新生成并确认后应结束等待流程")
    assert outline["title"] == "大纲 2"


def main() -> None:
    _assert_config_mapping()
    _assert_approve_flow()
    _assert_regenerate_flow()
    sys.stdout.write("✅ 快速/深度模式与报告大纲确认逻辑通过\n")


if __name__ == "__main__":
    main()
