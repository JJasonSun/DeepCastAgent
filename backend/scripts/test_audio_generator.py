import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from services.audio_generator import AudioGenerationService


class TestAudioGenerationService(unittest.TestCase):
    def setUp(self):
        self.mock_config = MagicMock()
        self.mock_config.tts_api_key = "test_key"
        self.mock_config.audio_output_dir = "./test_output"
        self.mock_config.tts_base_url = "http://test.api/tts"
        self.mock_config.tts_model = "test-tts"
        self.mock_config.tts_voice_design_model = "test-tts-voicedesign"
        self.mock_config.tts_timeout = 300
        self.mock_config.ffmpeg_path = "ffmpeg"

        # Patch Path.mkdir to avoid actual filesystem creation during init
        with patch('pathlib.Path.mkdir'):
            self.service = AudioGenerationService(self.mock_config)

    def test_generate_audio_success(self):
        script = [
            {"role": "Host", "content": "Hello world", "emotion": "好奇地追问"},
            {"role": "Guest", "content": "Hi host", "emotion": "微笑着回应", "audio_tag": "轻笑"}
        ]

        with patch.object(self.service, "_call_tts_api", return_value=True):
            files = self.service.generate_audio(script, "task_123")

        # Verify
        self.assertEqual(len(files), 2)
        self.assertTrue(files[0].endswith("task_123_000_Host.wav"))
        self.assertTrue(files[1].endswith("task_123_001_Guest.wav"))

    def test_generate_audio_no_api_key(self):
        self.mock_config.tts_api_key = None
        script = [{"role": "Host", "content": "Hello"}]

        files = self.service.generate_audio(script)
        self.assertEqual(files, [])

    def test_get_preset_voice(self):
        self.assertEqual(self.service._get_preset_voice("Host"), "苏打")
        self.assertEqual(self.service._get_preset_voice("苏打"), "苏打")
        self.assertEqual(self.service._get_preset_voice("Guest"), "茉莉")
        self.assertEqual(self.service._get_preset_voice("茉莉"), "茉莉")
        self.assertEqual(self.service._get_preset_voice("Unknown"), "苏打")

    def test_build_director_instruction(self):
        host_inst = self.service._build_director_instruction("Host", "好奇地追问")
        self.assertIn("角色", host_inst)
        self.assertIn("场景", host_inst)
        self.assertIn("指导", host_inst)
        self.assertIn("好奇地追问", host_inst)

        guest_inst = self.service._build_director_instruction("Guest", "")
        self.assertIn("角色", guest_inst)
        self.assertIn("自然", guest_inst)

    def test_embed_audio_tag(self):
        self.assertEqual(
            AudioGenerationService._embed_audio_tag("内容", "轻笑"),
            "(轻笑)内容"
        )
        self.assertEqual(
            AudioGenerationService._embed_audio_tag("内容", ""),
            "内容"
        )
        self.assertEqual(
            AudioGenerationService._embed_audio_tag("内容", None),
            "内容"
        )

    def test_voice_design_description(self):
        host_desc = self.service._get_voice_design_description("Host")
        self.assertIn("年轻成年男性", host_desc)
        self.assertIn("亲和清爽", host_desc)

        guest_desc = self.service._get_voice_design_description("Guest")
        self.assertIn("成年女性", guest_desc)
        self.assertIn("同一档节目质感", guest_desc)

    def test_normalize_emotion_and_audio_tag(self):
        emotion = self.service._normalize_emotion("兴奋地提高音量并语速加快")
        self.assertIn("轻快", emotion)
        self.assertIn("稍微加强语气", emotion)
        self.assertIn("节奏略快", emotion)

        self.assertEqual(
            AudioGenerationService._embed_audio_tag("内容", "提高音量"),
            "(轻声强调)内容"
        )


if __name__ == '__main__':
    unittest.main()
