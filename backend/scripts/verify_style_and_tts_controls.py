"""验证播客风格提示词与 TTS 声音一致性控制。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from config import Configuration
from services.audio_generator import AudioGenerationService
from services.script_generator import ScriptGenerationService


def _build_config(style: str, output_dir: str) -> Configuration:
    return Configuration.from_env(
        {
            "podcast_style": style,
            "audio_output_dir": output_dir,
            "llm_api_key": "fake-key",
            "tts_api_key": "fake-key",
        }
    )


def _build_audio_service(style: str, output_dir: str, *, enable_voice_design: bool = False) -> AudioGenerationService:
    config = Configuration.from_env(
        {
            "podcast_style": style,
            "audio_output_dir": output_dir,
            "llm_api_key": "fake-key",
            "tts_api_key": "fake-key",
            "enable_tts_voice_design": enable_voice_design,
        }
    )
    return AudioGenerationService(config)


def _assert_style_prompts(output_dir: str) -> None:
    expected = {
        "plain": ["通俗解释", "生活化类比", "复杂问题"],
        "professional": ["专业分析", "结构化判断", "信息密度"],
        "news": ["新闻播报", "事实优先", "节奏紧凑"],
    }
    for style, keywords in expected.items():
        service = ScriptGenerationService(_build_config(style, output_dir))
        instruction = service._build_style_instruction()
        for keyword in keywords:
            assert keyword in instruction


def _assert_tts_consistency(output_dir: str) -> None:
    service = _build_audio_service("plain", output_dir)
    assert service._use_voice_design is False
    assert _build_audio_service("plain", output_dir, enable_voice_design=True)._use_voice_design is True

    host_desc = service._get_voice_design_description("Host")
    guest_desc = service._get_voice_design_description("Guest")
    shared_keywords = ["同一档中文知识播客", "音量稳定", "不要夸张表演"]
    for keyword in shared_keywords:
        assert keyword in host_desc
        assert keyword in guest_desc

    context = service._build_conversation_context(
        [
            {"role": "Host", "content": "这件事为什么重要？"},
            {"role": "Guest", "content": "因为它会影响后续产品路线。"},
        ],
        0,
    )
    host_instruction = service._build_director_instruction("Host", "兴奋地提高音量并语速加快", "提高音量", context)
    assert "共同指导" in host_instruction
    assert "连续对话上下文" in host_instruction
    assert "稍微加强语气" in host_instruction
    assert "节奏略快" in host_instruction
    assert "提高音量" not in host_instruction

    assert AudioGenerationService._embed_audio_tag("内容", "提高音量") == "[轻声强调]内容"
    assert AudioGenerationService._embed_audio_tag("内容", "语速加快") == "[节奏略快]内容"


def main() -> None:
    with TemporaryDirectory() as tmp_dir:
        _assert_style_prompts(tmp_dir)
        _assert_tts_consistency(tmp_dir)
    sys.stdout.write("✅ 播客风格与 TTS 声音一致性控制通过\n")


if __name__ == "__main__":
    main()
