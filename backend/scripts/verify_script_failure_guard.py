"""验证脚本生成失败时会中断，不进入音频链路。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from agent import DeepResearchAgent
from config import Configuration
from models import SummaryState


class FakeDirector:
    """模拟 WriterAgent 脚本生成失败。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def dispatch(self, agent_name: str, context: dict) -> SimpleNamespace:
        self.calls.append((agent_name, context))
        return SimpleNamespace(success=False, data={"script": []})


class AudioGuard:
    """如果音频链路被调用，测试应立即失败。"""

    def generate_audio(self, *args: object, **kwargs: object) -> list[str]:
        raise AssertionError("脚本失败后不应进入 TTS 生成")

    def synthesize_podcast(self, *args: object, **kwargs: object) -> str | None:
        raise AssertionError("脚本失败后不应进入音频拼接")


def main() -> None:
    agent = object.__new__(DeepResearchAgent)
    agent.config = Configuration.from_env(
        {
            "enable_script_blueprint": False,
            "llm_api_key": "fake-key",
        }
    )
    agent.director = FakeDirector()
    agent.audio_generator = AudioGuard()
    agent.podcast_synthesizer = AudioGuard()
    agent._cancel_event = Event()

    state = SummaryState(research_topic="测试主题")
    state.structured_report = "测试报告"

    stream = agent._stream_script_phase(state)
    assert next(stream)["type"] == "stage_change"
    assert next(stream)["type"] == "log"
    assert next(stream)["type"] == "log"

    try:
        next(stream)
    except RuntimeError as exc:
        assert "脚本生成失败" in str(exc)
    else:
        raise AssertionError("脚本失败应触发 RuntimeError")

    assert state.podcast_script is None
    assert len(agent.director.calls) == 1
    assert agent.director.calls[0][0] == "writer"

    sys.stdout.write("✅ 脚本失败阻断下游音频链路通过\n")


if __name__ == "__main__":
    main()
