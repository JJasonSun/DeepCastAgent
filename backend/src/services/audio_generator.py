"""使用 TTS API 从文本生成音频的服务（导演模式 + VoiceDesign）。"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event

from openai import OpenAI

from config import Configuration

logger = logging.getLogger(__name__)


class AudioGenerationService:
    """处理与 MiMo TTS 服务的交互，支持导演模式和文本音色设计。"""

    # ── 音色设计描述（用于 VoiceDesign 模型） ──────────────────────
    _VOICE_DESIGN_HOST = (
        "一位二十多岁的年轻男性播客主持人，声音温暖明亮、富有亲和力，"
        "像一个好奇心旺盛的朋友在聊天，语速自然偏快，"
        "偶尔会因为兴奋而提高音量，带点幽默感和少年气。"
    )
    _VOICE_DESIGN_GUEST = (
        "一位三十岁左右的知性女性，声音清晰沉稳、略带磁性，"
        "像一位博学但不摆架子的学者，语速平稳从容，"
        "解释复杂概念时会放慢节奏、加重语气，偶尔流露出温柔的幽默。"
    )

    # ── 预置音色（降级方案） ────────────────────────────────────────
    _VOICE_HOST = "苏打"
    _VOICE_GUEST = "冰糖"

    # ── 导演模式角色描述 ────────────────────────────────────────────
    _DIRECTOR_HOST = (
        "角色：年轻男性播客主持人，好奇心强、幽默风趣，"
        "代表普通听众视角，善于用生活化比喻提问。\n\n"
        "场景：正在录制一档深度研究播客，与搭档进行双人对谈。"
    )
    _DIRECTOR_GUEST = (
        "角色：知性女性领域专家，博学严谨但不摆架子，"
        "擅长深入浅出地解释专业概念，偶尔用幽默化解术语。\n\n"
        "场景：正在录制一档深度研究播客，与搭档进行双人对谈。"
    )

    def __init__(self, config: Configuration) -> None:
        self._config = config
        self._output_dir = Path(config.audio_output_dir)
        self._ensure_output_dir()
        self._use_voice_design = bool(config.tts_voice_design_model)

    def _ensure_output_dir(self) -> None:
        if not self._output_dir.exists():
            try:
                self._output_dir.mkdir(parents=True, exist_ok=True)
                logger.info("Created audio output directory: %s", self._output_dir)
            except Exception as e:
                logger.error("Failed to create audio output directory: %s", e)

    def generate_audio(
        self,
        script: list[dict[str, str]],
        task_id: str = "default",
        progress_callback: Callable[[int, int, str, str], bool | None] | None = None,
        cancel_event: Event | None = None,
    ) -> list[str]:
        """为给定的脚本生成音频文件。"""
        if not self._config.tts_api_key:
            logger.warning("TTS API key not configured. Skipping audio generation.")
            return []

        generated_files = []
        total = len(script)

        for index, turn in enumerate(script):
            role = turn.get("role", "")
            content = turn.get("content", "")
            emotion = turn.get("emotion", "")
            audio_tag = turn.get("audio_tag", "")

            if not role or not content:
                continue

            if cancel_event and cancel_event.is_set():
                logger.info("Audio generation cancelled before TTS %d/%d", index + 1, total)
                break

            file_name = f"{task_id}_{index:03d}_{role}.wav"
            file_path = self._output_dir / file_name

            logger.info("[TTS %d/%d] %s: %s (emotion=%s)", index + 1, total, role, content[:20], emotion)

            if self._call_tts_api(content, role, emotion, audio_tag, file_path):
                generated_files.append(str(file_path))
                logger.info("[TTS %d/%d] %s 语音生成成功", index + 1, total, role)

                if cancel_event and cancel_event.is_set():
                    break

                if progress_callback:
                    content_preview = content[:30] + "..." if len(content) > 30 else content
                    should_continue = progress_callback(index + 1, total, role, content_preview)
                    if should_continue is False:
                        break
            else:
                logger.error("[TTS %d/%d] %s 语音生成失败", index + 1, total, role)

        logger.info("Generated %d audio files for task %s", len(generated_files), task_id)
        return generated_files

    # ── 导演模式 style 指令构建 ────────────────────────────────────

    def _build_director_instruction(self, role: str, emotion: str) -> str:
        """构建导演模式三段式 style 指令（角色/场景/指导）。"""
        if "host" in role.lower() or "苏打" in role:
            character_scene = self._DIRECTOR_HOST
        else:
            character_scene = self._DIRECTOR_GUEST

        if emotion:
            direction = f"指导：{emotion}。"
        else:
            direction = "指导：自然、有对话感地说话，像两个朋友在聊天。"

        return f"{character_scene}\n\n{direction}"

    # ── 音频标签嵌入 ──────────────────────────────────────────────

    @staticmethod
    def _embed_audio_tag(content: str, audio_tag: str) -> str:
        """将音频标签嵌入到文本开头。"""
        if audio_tag:
            return f"({audio_tag}){content}"
        return content

    # ── 音色获取 ──────────────────────────────────────────────────

    def _get_voice_design_description(self, role: str) -> str:
        """获取角色的音色设计描述。"""
        if "host" in role.lower() or "苏打" in role:
            return self._VOICE_DESIGN_HOST
        return self._VOICE_DESIGN_GUEST

    def _get_preset_voice(self, role: str) -> str:
        """获取预置音色名称（降级方案）。"""
        if "host" in role.lower() or "苏打" in role:
            return self._VOICE_HOST
        return self._VOICE_GUEST

    # ── TTS API 调用 ─────────────────────────────────────────────

    def _call_tts_api(
        self,
        text: str,
        role: str,
        emotion: str,
        audio_tag: str,
        output_path: Path,
    ) -> bool:
        """调用 MiMo TTS API 并保存音频文件。"""
        if output_path.exists():
            logger.debug("Audio file already exists: %s", output_path)
            return True

        try:
            client = OpenAI(
                api_key=self._config.tts_api_key,
                base_url=self._config.tts_base_url,
            )

            # 构建导演模式 style 指令
            style_instruction = self._build_director_instruction(role, emotion)

            # 嵌入音频标签到文本
            tts_text = self._embed_audio_tag(text, audio_tag)

            # 构建 messages
            messages = [
                {"role": "user", "content": style_instruction},
                {"role": "assistant", "content": tts_text},
            ]

            # 选择模型和音色
            if self._use_voice_design:
                model = self._config.tts_voice_design_model
                voice_description = self._get_voice_design_description(role)
                # VoiceDesign 模型：user message 用音色设计描述，无 audio.voice
                messages[0]["content"] = voice_description
                # 在音色描述后追加导演模式指令
                messages.insert(1, {"role": "user", "content": style_instruction})
                audio_params: dict = {"format": "wav"}
            else:
                model = self._config.tts_model
                voice = self._get_preset_voice(role)
                audio_params = {"format": "wav", "voice": voice}

            logger.debug("Calling MiMo TTS (model=%s) for %s: %s...", model, role, tts_text[:20])

            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                audio=audio_params,
                timeout=self._config.tts_timeout,
            )

            audio_data = completion.choices[0].message.audio
            if not audio_data or not audio_data.data:
                logger.error("MiMo TTS returned empty audio data")
                return False

            audio_bytes = base64.b64decode(audio_data.data)
            with open(output_path, "wb") as f:
                f.write(audio_bytes)

            return True

        except Exception as e:
            logger.exception("Exception during MiMo TTS API call: %s", e)
            return False
