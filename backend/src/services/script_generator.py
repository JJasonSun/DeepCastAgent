"""将研究报告转换为播客脚本的服务。"""

from __future__ import annotations

import json
import logging
import re

from openai import OpenAI

from config import Configuration
from models import SummaryState
from prompts import script_blueprint_instructions, script_writer_instructions

logger = logging.getLogger(__name__)

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


# 播客脚本的 JSON Schema
SCRIPT_JSON_SCHEMA = {
    "type": "array",
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
    "minItems": 8,
    "maxItems": 18
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
        )
        # 使用 fast_llm_model（ecnu-max）进行脚本生成，它支持结构化输出
        self._model = config.fast_llm_model or "ecnu-max"

    def generate_script(self, state: SummaryState) -> list[dict[str, str]]:
        """基于结构化报告生成播客脚本（使用结构化输出）。"""
        if not state.structured_report:
            logger.warning("No structured report available for script generation.")
            return []
        
        report_length = len(state.structured_report)
        logger.info("Generating script from report (%d chars) using structured output...", report_length)

        blueprint = self._generate_blueprint(state.structured_report)
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
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": script_writer_instructions.strip()},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=4096,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "podcast_script",
                        "schema": SCRIPT_JSON_SCHEMA
                    },
                },
            )
            
            content = response.choices[0].message.content
            logger.info("Received structured response (%d chars)", len(content) if content else 0)
            
            if not content:
                logger.error("Empty response from LLM")
                return []
            
            # 尝试解析 JSON（处理各种格式问题）
            script = self._parse_script_json(content)
            
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
                    elif role.lower() in ["guest", "冰糖", "茉莉"]:
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
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": script_blueprint_instructions.strip()},
                    {"role": "user", "content": f"<RESEARCH_REPORT>\n{report}\n</RESEARCH_REPORT>"},
                ],
                temperature=0.4,
                max_tokens=2048,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "podcast_blueprint",
                        "schema": SCRIPT_BLUEPRINT_JSON_SCHEMA,
                    },
                },
            )
            content = response.choices[0].message.content
            if not content:
                logger.warning("Empty podcast blueprint response; falling back to direct script generation.")
                return None
            blueprint = json.loads(content)
            if isinstance(blueprint, dict):
                logger.info(
                    "Generated podcast blueprint: %s",
                    blueprint.get("title", "untitled"),
                )
                return blueprint
        except Exception as e:
            logger.warning("Podcast blueprint generation failed; falling back to direct script generation: %s", e)
        return None

    def _parse_script_json(self, content: str) -> list | None:
        """
        尝试多种方式解析脚本 JSON。
        
        Args:
            content: LLM 返回的原始内容
            
        Returns:
            解析后的列表，失败返回 None
        """
        # 1. 直接尝试解析
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.debug("Direct JSON parse failed at char %d: %s", e.pos, e.msg)
        
        # 2. 尝试从 markdown 代码块中提取
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            try:
                result = json.loads(json_match.group(1).strip())
                logger.info("Extracted JSON from markdown code block")
                return result
            except json.JSONDecodeError:
                pass
        
        # 3. 提取 JSON 数组部分
        start_idx = content.find('[')
        end_idx = content.rfind(']')
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            json_str = content[start_idx:end_idx + 1]
            
            # 3a. 直接尝试
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.debug("Array extraction failed at char %d: %s", e.pos, e.msg)
                # 记录出错位置附近的内容
                error_start = max(0, e.pos - 50)
                error_end = min(len(json_str), e.pos + 50)
                logger.debug("Content around error: ...%s...", json_str[error_start:error_end])
            
            # 3b. 尝试修复常见问题
            fixed_json = self._fix_json_issues(json_str)
            try:
                result = json.loads(fixed_json)
                logger.info("Parsed JSON after fixing common issues")
                return result
            except json.JSONDecodeError:
                pass
        
        # 4. 最后尝试：逐个对象解析
        result = self._parse_objects_individually(content)
        if result:
            logger.info("Parsed %d objects individually", len(result))
            return result
        
        logger.error("Could not parse JSON from response. First 500 chars: %s", content[:500])
        return None
    
    def _fix_json_issues(self, json_str: str) -> str:
        """尝试修复常见的 JSON 格式问题。"""
        fixed = json_str
        
        # 替换中文引号为英文引号
        fixed = fixed.replace('"', '"').replace('"', '"')
        fixed = fixed.replace(''', "'").replace(''', "'")
        
        # 移除可能的 BOM 或其他不可见字符
        fixed = fixed.strip('\ufeff\u200b\u200c\u200d')
        
        # 修复未转义的换行符（在字符串值内）
        # 这是一个简化的修复，可能不完美
        def escape_newlines_in_strings(match):
            return match.group(0).replace('\n', '\\n').replace('\r', '\\r')
        
        # 匹配 JSON 字符串值
        fixed = re.sub(r'"[^"]*"', escape_newlines_in_strings, fixed)
        
        return fixed
    
    def _parse_objects_individually(self, content: str) -> list | None:
        """
        尝试逐个解析 JSON 对象。

        当整体解析失败时，尝试提取每个 {role, content, ...} 对象。
        """
        results = []

        # 匹配完整的 JSON 对象（从 { 到 }），然后尝试 json.loads
        obj_pattern = r'\{[^{}]*\}'
        for match in re.finditer(obj_pattern, content, re.DOTALL):
            try:
                obj = json.loads(match.group(0))
                if isinstance(obj, dict) and "role" in obj and "content" in obj:
                    results.append(obj)
            except json.JSONDecodeError:
                pass

        if results:
            return results

        # 回退：匹配最基本的 {"role": "...", "content": "..."} 模式
        pattern = r'\{\s*"role"\s*:\s*"(Host|Guest)"\s*,\s*"content"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
        for match in re.finditer(pattern, content, re.DOTALL):
            role = match.group(1)
            content_text = match.group(2)
            try:
                content_text = json.loads(f'"{content_text}"')
            except Exception:
                pass
            results.append({"role": role, "content": content_text})
        
        if results:
            return results
        
        return None
