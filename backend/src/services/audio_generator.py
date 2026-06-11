"""使用 TTS API 从文本生成音频的服务（导演模式 + VoiceDesign）。"""

from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from pathlib import Path
from threading import Event

from openai import OpenAI

from config import Configuration
from services.llm import run_with_retry

logger = logging.getLogger(__name__)


class AudioGenerationService:
    """处理与 MiMo TTS 服务的交互，支持导演模式和文本音色设计。"""

    # ── 音色设计描述（用于 VoiceDesign 模型） ──────────────────────
    _VOICE_DESIGN_SHARED = (
        "声音来自同一档中文知识播客，录音棚质感干净，口播自然，"
        "音量稳定，语速中等略快，情绪表达克制但有温度，"
        "不要夸张表演，不要突然提高音量或大幅改变语速。"
    )
    _VOICE_DESIGN_HOST = (
        f"{_VOICE_DESIGN_SHARED}"
        "年轻成年男性播客主持人，音色温暖明亮、亲和清爽，"
        "提问时带一点好奇和轻微笑意，像认真聆听的搭档，"
        "表达轻快但不跳脱，和女嘉宾保持同一档节目质感。"
    )
    _VOICE_DESIGN_GUEST = (
        f"{_VOICE_DESIGN_SHARED}"
        "成年女性播客嘉宾，音色温暖清亮、稳定清晰，"
        "解释时有专业感和亲和力，重点处可以稍作停顿，"
        "语气不端着、不拖慢，和男主持保持同一档节目质感。"
    )

    # ── 预置音色（降级方案） ────────────────────────────────────────
    _VOICE_HOST = "苏打"
    _VOICE_GUEST = "茉莉"

    # ── 导演模式角色描述 ────────────────────────────────────────────
    _DIRECTOR_HOST = (
        "角色：年轻成年男性播客主持人，亲和、好奇、善于追问，"
        "代表普通听众视角，用生活化比喻帮助理解。\n\n"
        "场景：正在录制一档中文知识播客，与搭档进行双人对谈。"
    )
    _DIRECTOR_GUEST = (
        "角色：成年女性领域嘉宾，专业、清晰、亲和，"
        "擅长深入浅出解释专业概念，回应主持人的追问。\n\n"
        "场景：正在录制一档中文知识播客，与搭档进行双人对谈。"
    )
    _DIRECTOR_SHARED_GUIDANCE = (
        "共同指导：保持同一档节目的录音棚口播质感；"
        "语速中等略快，音量稳定，情绪自然克制；"
        "只做轻微语气变化，不要大喊、不要突然加速、不要过度表演。"
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
        if self._is_guest_role(role):
            character_scene = self._DIRECTOR_GUEST
            default_direction = (
                "指导：语气稳定清晰，有专业感和亲和力。"
                "解释概念时可在关键点稍作停顿，但不要显得端着或拖慢。"
            )
        else:
            character_scene = self._DIRECTOR_HOST
            default_direction = (
                "指导：语气轻快、有好奇感，像自然地把问题递给搭档。"
                "总结时稍微放慢强调，但整体不要跳脱。"
            )

        if emotion:
            direction = (
                f"指导：参考情绪“{self._normalize_emotion(emotion)}”，"
                "但只做轻微表达变化，保持语速和音量稳定。"
            )
        else:
            direction = default_direction

        return f"{character_scene}\n\n{self._DIRECTOR_SHARED_GUIDANCE}\n\n{direction}"

    # ── 音频标签嵌入 ──────────────────────────────────────────────

    @staticmethod
    def _embed_audio_tag(content: str, audio_tag: str) -> str:
        """将音频标签嵌入到文本开头。"""
        if audio_tag:
            normalized_tag = AudioGenerationService._normalize_audio_tag(audio_tag)
            if normalized_tag:
                return f"({normalized_tag}){content}"
        return content

    @staticmethod
    def _normalize_emotion(emotion: str) -> str:
        """收敛脚本情绪描述，避免 TTS 出现过大语速或音量差异。"""
        replacements = {
            "提高音量": "稍微加强语气",
            "加大音量": "稍微加强语气",
            "大声": "清晰强调",
            "喊": "清晰强调",
            "语速加快": "节奏略快",
            "加快语速": "节奏略快",
            "快速": "略快",
            "兴奋": "轻快",
            "激动": "轻快",
            "夸张": "自然",
            "大笑": "轻笑",
        }
        normalized = emotion.strip()
        for source, target in replacements.items():
            normalized = normalized.replace(source, target)
        return normalized

    @staticmethod
    def _normalize_audio_tag(audio_tag: str) -> str:
        """把强控制标签改写为更温和的 TTS 表现标签。"""
        tag = audio_tag.strip()
        tag_map = {
            "提高音量": "轻声强调",
            "加大音量": "轻声强调",
            "语速加快": "节奏略快",
            "节奏加快": "节奏略快",
            "深呼吸": "稍作停顿",
            "沉默片刻": "稍作停顿",
            "叹气": "稍作停顿",
            "大笑": "轻笑",
        }
        return tag_map.get(tag, tag)

    # ── 音色获取 ──────────────────────────────────────────────────

    def _get_voice_design_description(self, role: str) -> str:
        """获取角色的音色设计描述。"""
        if self._is_guest_role(role):
            return self._VOICE_DESIGN_GUEST
        return self._VOICE_DESIGN_HOST

    def _get_preset_voice(self, role: str) -> str:
        """获取预置音色名称（降级方案）。"""
        if self._is_guest_role(role):
            return self._VOICE_GUEST
        return self._VOICE_HOST

    @staticmethod
    def _is_host_role(role: str) -> bool:
        """判断是否为 Host 角色。"""
        return "host" in role.lower() or "苏打" in role

    @staticmethod
    def _is_guest_role(role: str) -> bool:
        """判断是否为 Guest 角色。"""
        return "guest" in role.lower() or "茉莉" in role

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
                max_retries=0,
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

            completion = run_with_retry(
                lambda: client.chat.completions.create(
                    model=model,
                    messages=messages,
                    audio=audio_params,
                    timeout=self._config.tts_timeout,
                ),
                operation_name=f"MiMo TTS ({role})",
                max_retries=self._config.tts_max_retries,
                retry_base_delay=self._config.llm_retry_base_delay,
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
