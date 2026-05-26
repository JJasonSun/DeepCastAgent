"""将研究报告转换为播客脚本的服务。"""

from __future__ import annotations

import json
import logging

from openai import OpenAI

from config import Configuration
from models import SummaryState
from prompts import script_blueprint_instructions, script_writer_instructions
from services.llm import call_llm_json

logger = logging.getLogger(__name__)
MAX_BLUEPRINT_SECTIONS = 3

# 播客节目蓝图的 JSON Schema
SCRIPT_BLUEPRINT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "本期节目标题"
        },
        "target_listener": {
            "type": "string",
            "description": "目标听众画像"
        },
        "tone": {
            "type": "string",
            "description": "节目语气、节奏和听感要求"
        },
        "hook": {
            "type": "string",
            "description": "前 15 秒吸引听众的开场 Hook"
        },
        "sections": {
            "type": "array",
            "description": "主体话题段落",
            "items": {
                "type": "object",
                "properties": {
                    "segment_title": {
                        "type": "string",
                        "description": "段落标题"
                    },
                    "listener_question": {
                        "type": "string",
                        "description": "本段要替听众回答的问题"
                    },
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "本段必须覆盖的关键事实、案例或观点"
                    },
                    "host_questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Host 可以提出的追问"
                    },
                    "transition": {
                        "type": "string",
                        "description": "承接本段并引出下一段的转场逻辑"
                    },
                },
                "required": [
                    "segment_title",
                    "listener_question",
                    "key_points",
                    "host_questions",
                    "transition",
                ],
            },
            "minItems": 3,
            "maxItems": 3,
        },
        "closing": {
            "type": "string",
            "description": "结尾总结逻辑"
        },
        "cta": {
            "type": "string",
            "description": "自然的行动号召"
        },
    },
    "required": [
        "title",
        "target_listener",
        "tone",
        "hook",
        "sections",
        "closing",
        "cta",
    ],
}


# 播客脚本的 JSON Schema。DeepSeek JSON Output 使用 json_object，因此顶层必须是对象。
SCRIPT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "turns": {
            "type": "array",
            "description": "播客对话轮次",
            "items": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["Host", "Guest"],
                        "description": "对话角色，Host 为主持人，Guest 为嘉宾"
                    },
                    "content": {
                        "type": "string",
                        "description": "对话内容"
                    },
                    "emotion": {
                        "type": "string",
                        "description": "说话时的情绪状态和说话方式，如：好奇地追问、兴奋地分享、若有所思地回应、忍不住轻笑"
                    },
                    "audio_tag": {
                        "type": "string",
                        "description": "可选的音频风格标签，控制细粒度语音表现，如：轻笑、叹气、语速加快、提高音量、放慢语速"
                    }
                },
                "required": ["role", "content", "emotion"]
            },
        }
    },
    "required": ["turns"],
}


class ScriptGenerationService:
    """从研究报告生成对话脚本（使用结构化输出）。"""

    def __init__(
        self,
        config: Configuration,
        script_agent: OpenAI | None = None,
    ) -> None:
        """
        初始化服务。

        Args:
            config: 全局配置对象。
            script_agent: 可选的自定义脚本生成客户端/代理。
                如果提供，将直接使用该客户端；否则将基于配置创建默认的 OpenAI 客户端。
        """
        self._config = config
        # 优先使用注入的自定义客户端，以保持向后兼容和可测试性；
        # 如果未提供，则基于配置创建默认的 OpenAI 客户端以支持结构化输出。
        self._client = script_agent or OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
            timeout=config.llm_timeout,
            max_retries=0,
        )
        self._model = config.active_llm_model()

    def generate_blueprint(self, state: SummaryState) -> dict | None:
        """基于研究报告生成可展示的节目蓝图。"""
        if not state.structured_report:
            logger.warning("No structured report available for podcast blueprint generation.")
            return None
        blueprint = self._generate_blueprint(state.structured_report)
        state.podcast_blueprint = blueprint
        return blueprint

    def generate_script(
        self,
        state: SummaryState,
        blueprint: dict | None = None,
    ) -> list[dict[str, str]]:
        """基于结构化报告生成播客脚本（使用结构化输出）。"""
        if not state.structured_report:
            logger.warning("No structured report available for script generation.")
            return []
        
        report_length = len(state.structured_report)
        logger.info("Generating script from report (%d chars) using structured output...", report_length)

        if blueprint is None:
            blueprint = state.podcast_blueprint or self._generate_blueprint(state.structured_report)
        state.podcast_blueprint = blueprint

        blueprint_block = ""
        if blueprint:
            blueprint_block = (
                "<PODCAST_BLUEPRINT>\n"
                f"{json.dumps(blueprint, ensure_ascii=False, indent=2)}\n"
                "</PODCAST_BLUEPRINT>\n\n"
            )

        user_prompt = (
            f"{blueprint_block}"
            f"<RESEARCH_REPORT>\n{state.structured_report}\n</RESEARCH_REPORT>"
        )
        try:
            result = call_llm_json(
                client=self._client,
                system_prompt=script_writer_instructions.strip(),
                user_prompt=user_prompt,
                model=self._model,
                json_schema=SCRIPT_JSON_SCHEMA,
                schema_name="podcast_script",
                temperature=0.7,
                max_tokens=4096,
                extra_body=self._config.build_thinking_body(enable=False),
                max_retries=self._config.llm_max_retries,
                retry_base_delay=self._config.llm_retry_base_delay,
                timeout=self._config.llm_long_timeout,
                response_transform=self._normalize_blueprint,
            )

            if not result:
                logger.error("Empty response from LLM")
                return []

            script = self._extract_turns(result)
            if script is None:
                return []

            if not isinstance(script, list):
                logger.error("Script output is not a list: %s", type(script))
                return []

            # 验证并标准化
            valid_script = []
            for item in script:
                if isinstance(item, dict) and "role" in item and "content" in item:
                    role = item["role"]
                    content = item["content"]
                    # 标准化角色名
                    if role.lower() in ["host", "苏打"]:
                        role = "Host"
                    elif role.lower() in ["guest", "茉莉"]:
                        role = "Guest"
                    entry = {"role": role, "content": content}
                    # 保留可选的情感和音频标签字段
                    if item.get("emotion"):
                        entry["emotion"] = str(item["emotion"]).strip()
                    if item.get("audio_tag"):
                        entry["audio_tag"] = str(item["audio_tag"]).strip()
                    valid_script.append(entry)

            logger.info("Generated script with %d dialogue turns.", len(valid_script))
            return valid_script
        except json.JSONDecodeError as e:
            logger.error("JSON decode error (should not happen with structured output): %s", e)
            return []
        except Exception as e:
            logger.error("Script generation failed: %s", e)
            return []

    def _generate_blueprint(self, report: str) -> dict | None:
        """先生成节目蓝图，用于约束后续对话脚本的结构和节奏。"""
        if not self._config.enable_script_blueprint:
            return None

        try:
            result = call_llm_json(
                client=self._client,
                system_prompt=script_blueprint_instructions.strip(),
                user_prompt=f"<RESEARCH_REPORT>\n{report}\n</RESEARCH_REPORT>",
                model=self._model,
                json_schema=SCRIPT_BLUEPRINT_JSON_SCHEMA,
                schema_name="podcast_blueprint",
                temperature=0.4,
                max_tokens=2048,
                extra_body=self._config.build_thinking_body(enable=False),
                max_retries=self._config.llm_max_retries,
                retry_base_delay=self._config.llm_retry_base_delay,
                timeout=self._config.llm_long_timeout,
            )
            if isinstance(result, dict):
                logger.info(
                    "Generated podcast blueprint: %s",
                    result.get("title", "untitled"),
                )
                return result
        except Exception as e:
            logger.warning("Podcast blueprint generation failed; falling back to direct script generation: %s", e)
        return None

    @staticmethod
    def _normalize_blueprint(payload: object) -> object:
        """容忍模型多生成节目段落，只保留前 3 段进入 schema 校验。"""
        if not isinstance(payload, dict):
            return payload
        sections = payload.get("sections")
        if isinstance(sections, list) and len(sections) > MAX_BLUEPRINT_SECTIONS:
            logger.warning(
                "Podcast blueprint returned %d sections; truncating to %d.",
                len(sections),
                MAX_BLUEPRINT_SECTIONS,
            )
            payload = {**payload, "sections": sections[:MAX_BLUEPRINT_SECTIONS]}
        return payload

    @staticmethod
    def _extract_turns(payload: dict | list) -> list | None:
        """从 DeepSeek JSON object 输出中提取对话数组，并兼容旧数组格式。"""
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return None
        for key in ("turns", "script", "dialogue", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return None
