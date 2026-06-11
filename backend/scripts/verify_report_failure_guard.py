"""验证报告失败时会在报告阶段中断，不进入后续音频链路。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from agent import DeepResearchAgent
from config import Configuration
from models import SummaryState


class FakeDirector:
    """模拟 WriterAgent 返回空报告。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def dispatch(self, agent_name: str, context: dict) -> SimpleNamespace:
        self.calls.append((agent_name, context))
        return SimpleNamespace(success=False, data={"report": ""})


class AudioGuard:
    """如果音频链路被调用，测试应立即失败。"""

    def generate_audio(self, *args: object, **kwargs: object) -> list[str]:
        raise AssertionError("报告失败后不应进入 TTS 生成")

    def synthesize_podcast(self, *args: object, **kwargs: object) -> str | None:
        raise AssertionError("报告失败后不应进入音频拼接")


def main() -> None:
    agent = object.__new__(DeepResearchAgent)
    agent.config = Configuration.from_env({"max_report_refine_rounds": 1})
    agent.director = FakeDirector()
    agent.audio_generator = AudioGuard()
    agent.podcast_synthesizer = AudioGuard()

    state = SummaryState(research_topic="测试主题")
    try:
        agent._generate_report_via_agents_stream(state)
    except RuntimeError as exc:
        assert "报告生成失败" in str(exc)
    else:
        raise AssertionError("空报告应触发 RuntimeError")

    assert state.structured_report is None
    assert len(agent.director.calls) == 1
    assert agent.director.calls[0][0] == "writer"

    sys.stdout.write("✅ 报告失败阻断下游音频链路通过\n")


if __name__ == "__main__":
    main()
