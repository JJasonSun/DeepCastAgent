"""使用 TTS API 从文本生成音频的服务。"""

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
    """处理与 TTS 服务的交互以生成音频文件。"""

    # MiMo TTS 预置音色
    _VOICE_HOST = "苏打"    # 男声主持人
    _VOICE_GUEST = "冰糖"   # 女声嘉宾

    # 风格控制指令（放在 MiMo TTS 的 user message 中）
    _HOST_STYLE = "用温暖、活泼、略带幽默的语气说话，语速适中"
    _GUEST_STYLE = "用专业、清晰、沉稳的语气说话，表达准确"

    def __init__(self, config: Configuration) -> None:
        """
        初始化音频生成服务。

        Args:
            config: 包含 TTS 配置和输出路径的配置对象。
        """
        self._config = config
        self._output_dir = Path(config.audio_output_dir)
        self._ensure_output_dir()

    def _ensure_output_dir(self) -> None:
        """
        如果输出目录不存在，则创建它。
        
        同时处理创建目录时的潜在权限错误。
        """
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
        """
        为给定的脚本生成音频文件。
        
        Args:
            script: 对话回合列表，例如 [{"role": "Host", "content": "..."}, ...]
            task_id: 当前任务/会话的唯一标识符
            progress_callback: 可选的进度回调函数，签名为 (current, total, role, content_preview) -> Optional[bool]
                              返回 False 表示应该停止生成，返回 True 或 None 表示继续
            cancel_event: 可选的取消事件，set 时立即停止生成
            
        Returns:
            生成的音频文件的路径列表
        """
        # 检查FFmpeg路径是否配置
        if not self._config.ffmpeg_path:
            logger.error("FFmpeg path not configured. Audio generation will fail.")
            return []
        if not self._config.tts_api_key:
            logger.warning("TTS API key not configured. Skipping audio generation.")
            return []

        generated_files = []
        total = len(script)
        
        for index, turn in enumerate(script):
            role = turn.get("role", "")
            content = turn.get("content", "")
            
            if not role or not content:
                continue

            # 直接检查取消事件（最可靠的方式）
            if cancel_event and cancel_event.is_set():
                logger.info("Audio generation cancelled before TTS %d/%d (cancel_event)", index + 1, total)
                break
                
            voice_id = self._get_voice_for_role(role)
            
            file_name = f"{task_id}_{index:03d}_{role}.wav"
            file_path = self._output_dir / file_name
            
            logger.info("[TTS %d/%d] 正在为 %s 生成语音: %s...", index + 1, total, role, content[:20])
            
            if self._call_tts_api(content, voice_id, role, file_path):
                generated_files.append(str(file_path))
                logger.info("[TTS %d/%d] ✓ %s 语音生成成功", index + 1, total, role)
                
                # TTS 完成后再次检查取消
                if cancel_event and cancel_event.is_set():
                    logger.info("Audio generation cancelled after TTS %d/%d (cancel_event)", index + 1, total)
                    break
                
                # 在 TTS 成功之后才调用进度回调，通知上层该片段已完成
                if progress_callback:
                    content_preview = content[:30] + "..." if len(content) > 30 else content
                    should_continue = progress_callback(index + 1, total, role, content_preview)
                    if should_continue is False:
                        logger.info("Audio generation cancelled by callback after TTS %d/%d", index + 1, total)
                        break
            else:
                logger.error("[TTS %d/%d] ✗ %s 语音生成失败", index + 1, total, role)
                
        logger.info("Generated %d audio files for task %s", len(generated_files), task_id)
        return generated_files

    def _get_voice_for_role(self, role: str) -> str:
        """
        将角色名称映射到 MiMo TTS 预置音色。

        Args:
            role: 角色名称（如 Host, Guest）。

        Returns:
            对应的 MiMo 音色名称。
        """
        role_lower = role.lower()
        if "host" in role_lower or "苏打" in role:
            return self._VOICE_HOST
        elif "guest" in role_lower or "冰糖" in role:
            return self._VOICE_GUEST
        return self._VOICE_HOST

    def _build_style_instruction(self, role: str) -> str:
        """
        根据角色构建 MiMo TTS 风格控制指令。

        Args:
            role: 角色名称（如 Host, Guest）。

        Returns:
            风格控制自然语言指令。
        """
        role_lower = role.lower()
        if "host" in role_lower or "苏打" in role:
            return self._HOST_STYLE
        elif "guest" in role_lower or "冰糖" in role:
            return self._GUEST_STYLE
        return ""

    def _call_tts_api(self, text: str, voice: str, role: str, output_path: Path) -> bool:
        """
        调用 MiMo TTS API 并保存音频文件。

        Args:
            text: 要转换的文本。
            voice: MiMo 预置音色名称（如 苏打、冰糖）。
            role: 角色名称（如 Host, Guest），用于风格控制。
            output_path: 输出文件路径（.wav）。

        Returns:
            如果成功生成并保存，返回 True；否则返回 False。
        """
        if output_path.exists():
            logger.debug("Audio file already exists: %s", output_path)
            return True

        try:
            client = OpenAI(
                api_key=self._config.tts_api_key,
                base_url=self._config.tts_base_url,
            )

            style_instruction = self._build_style_instruction(role)

            messages = [
                {"role": "assistant", "content": text},
            ]
            if style_instruction:
                messages.insert(0, {"role": "user", "content": style_instruction})

            logger.debug("Calling MiMo TTS for voice %s: %s...", voice, text[:20])

            completion = client.chat.completions.create(
                model=self._config.tts_model,
                messages=messages,
                audio={"format": "wav", "voice": voice},
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
