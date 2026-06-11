"""验证片头 BGM 独立播放后再进入人声。"""

# ruff: noqa: E402

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_ROOT / "src"))

from config import Configuration
from services.audio_synthesizer import PodcastSynthesisService


def _duration_ms(path: Path) -> int:
    return len(AudioSegment.from_file(path))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="deepcast_bgm_") as tmp:
        tmp_dir = Path(tmp)
        bgm_path = tmp_dir / "intro_bgm.wav"
        seg1_path = tmp_dir / "voice_001.wav"
        seg2_path = tmp_dir / "voice_002.wav"

        Sine(220).to_audio_segment(duration=8000).apply_gain(-12).export(bgm_path, format="wav")
        Sine(440).to_audio_segment(duration=900).apply_gain(-18).export(seg1_path, format="wav")
        Sine(554).to_audio_segment(duration=900).apply_gain(-18).export(seg2_path, format="wav")

        config = Configuration.from_env(
            {
                "audio_output_dir": str(tmp_dir),
                "enable_intro_bgm": True,
                "intro_bgm_path": str(bgm_path),
                "intro_bgm_duration_ms": 8000,
                "intro_bgm_gain_db": -21,
                "intro_bgm_lead_in_ms": 400,
            }
        )
        output_path = PodcastSynthesisService(config).synthesize_podcast(
            [str(seg1_path), str(seg2_path)],
            task_id="intro_bgm_verify",
        )
        assert output_path is not None

        duration = _duration_ms(Path(output_path))
        expected = 8000 + 400 + 900 + 500 + 900
        assert abs(duration - expected) <= 120, (duration, expected)

    sys.stdout.write("✅ BGM 片头拼接逻辑通过\n")


if __name__ == "__main__":
    main()
