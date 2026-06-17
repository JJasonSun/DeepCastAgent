import os
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Define backend root directory
BACKEND_ROOT = Path(__file__).resolve().parent.parent

class SearchAPI(Enum):
    """搜索 API 提供商的枚举。

    兼容旧测试和示例：
    - TAVILY: 使用 Tavily 搜索后端
    - SERPAPI: 使用 SerpApi
    - DDG: DuckDuckGo (内置 ddgs)
    - HYBRID: 混合策略（Tavily + SerpApi），为默认值
    """
    TAVILY = "tavily"
    SERPAPI = "serpapi"
    DDG = "ddg"
    HYBRID = "hybrid"


class Configuration(BaseModel):
    """DeepCast Agent Configuration."""

    max_web_research_loops: int = Field(
        default=3,
        title="Research Depth",
        description="Number of research iterations",
    )
    search_api: SearchAPI = Field(
        default=SearchAPI.HYBRID,
        title="搜索 API",
        description="使用混合搜索引擎 (Tavily + SerpApi)",
    )
    enable_notes: bool = Field(
        default=True,
        title="启用笔记",
        description="是否在 NoteTool 中存储任务进度",
    )
    notes_workspace: str = Field(
        default=str(BACKEND_ROOT / "output" / "notes"),
        title="笔记工作区",
        description="NoteTool 持久化任务笔记的目录",
    )
    include_raw_source_content: bool = Field(
        default=False,
        title="包含原始来源正文",
        description="是否请求搜索后端返回 raw_content，并在可用时拼入研究上下文；不会主动抓取网页全文",
    )
    strip_thinking_tokens: bool = Field(
        default=False,
        title="移除思考 Token",
        description="是否从模型响应中移除 <think> token",
    )
    llm_api_key: str | None = Field(
        default=None,
        title="LLM API 密钥",
        description="使用自定义 OpenAI 兼容服务时的可选 API 密钥",
    )
    llm_base_url: str | None = Field(
        default=None,
        title="LLM 基础 URL",
        description="使用自定义 OpenAI 兼容服务时的可选基础 URL",
    )
    llm_model_id: str | None = Field(
        default="deepseek-v4-flash",
        title="LLM 模型 ID",
        description="当前任务使用的 DeepSeek 模型 ID",
    )
    llm_reasoning_effort: str = Field(
        default="high",
        title="LLM 思考强度",
        description="DeepSeek 思考模式推理强度 (high/max)",
    )
    tts_api_key: str | None = Field(
        default=None,
        title="TTS API 密钥",
        description="TTS 服务的 API 密钥",
    )
    tts_base_url: str = Field(
        default="https://api.xiaomimimo.com/v1",
        title="TTS 基础 URL",
        description="TTS API 的基础 URL",
    )
    tts_model: str = Field(
        default="mimo-v2.5-tts",
        title="TTS 模型",
        description="TTS 服务的模型标识符",
    )
    tts_voice_design_model: str = Field(
        default="mimo-v2.5-tts-voicedesign",
        title="TTS 音色设计模型",
        description="通过文本描述自定义音色的 TTS 模型 ID",
    )
    enable_tts_voice_design: bool = Field(
        default=False,
        title="启用 TTS 音色设计",
        description="是否使用 VoiceDesign 模型；默认使用预置音色以获得更稳定的真人感",
    )
    audio_output_dir: str = Field(
        default=str(BACKEND_ROOT / "output" / "audio"),
        title="音频输出目录",
        description="保存生成的音频文件的目录",
    )
    enable_intro_bgm: bool = Field(
        default=True,
        title="启用片头 BGM",
        description="是否在最终播客开头叠加短背景音乐",
    )
    intro_bgm_path: str | None = Field(
        default=str(BACKEND_ROOT / "assets" / "audio" / "intro_bgm.mp3"),
        title="片头 BGM 路径",
        description="用于播客开头的短背景音乐文件路径",
    )
    intro_bgm_duration_ms: int = Field(
        default=8000,
        title="片头 BGM 时长",
        description="片头背景音乐使用的最大时长（毫秒）",
    )
    intro_bgm_gain_db: float = Field(
        default=-21.0,
        title="片头 BGM 音量",
        description="叠加到人声下方时对 BGM 应用的增益（dB）",
    )
    intro_bgm_lead_in_ms: int = Field(
        default=400,
        title="片头留白",
        description="在第一句人声前加入的片头留白时长（毫秒）",
    )
    ffmpeg_path: str | None = Field(
        default=None,
        title="FFmpeg 路径",
        description="ffmpeg 可执行文件的路径",
    )
    tavily_api_key: str | None = Field(
        default=None,
        title="Tavily API 密钥",
        description="Tavily 搜索的 API 密钥",
    )
    serpapi_api_key: str | None = Field(
        default=None,
        title="SerpApi 密钥",
        description="SerpApi 的 API 密钥",
    )
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:5174,http://localhost:5175,http://127.0.0.1:5173,http://127.0.0.1:5174,http://127.0.0.1:5175,http://localhost:3000",
        title="CORS 允许的源",
        description="逗号分隔的允许跨域请求的源列表",
    )
    host: str = Field(
        default="0.0.0.0",
        title="服务器主机",
        description="FastAPI 服务器监听的主机地址",
    )
    port: int = Field(
        default=8000,
        title="服务器端口",
        description="FastAPI 服务器监听的端口",
    )
    log_level: str = Field(
        default="INFO",
        title="日志级别",
        description="日志记录级别 (DEBUG, INFO, WARNING, ERROR)",
    )
    llm_timeout: int = Field(
        default=60,
        title="LLM 超时",
        description="LLM 请求超时时间（秒）",
    )
    llm_long_timeout: int = Field(
        default=180,
        title="LLM 长任务超时",
        description="规划、报告、评审、脚本等长耗时 LLM 请求的超时时间（秒）",
    )
    llm_max_retries: int = Field(
        default=3,
        title="LLM 最大重试次数",
        description="LLM 网络连接、超时、限流或 5xx 错误的应用层重试次数",
    )
    llm_retry_base_delay: float = Field(
        default=1.0,
        title="LLM 重试基础等待",
        description="LLM 重试指数退避的基础等待秒数",
    )
    tts_timeout: int = Field(
        default=300,
        title="TTS 超时",
        description="TTS 请求超时时间（秒）",
    )
    tts_max_retries: int = Field(
        default=3,
        title="TTS 最大重试次数",
        description="TTS 网络连接、超时、限流或 5xx 错误的应用层重试次数",
    )
    search_max_retries: int = Field(
        default=2,
        title="搜索最大重试次数",
        description="搜索 API 网络连接、超时、限流或 5xx 错误的应用层重试次数",
    )
    sse_heartbeat_interval: int = Field(
        default=15,
        title="SSE 心跳间隔",
        description="流式接口无业务事件时向前端发送 heartbeat 的间隔秒数",
    )
    workflow_max_seconds: int = Field(
        default=1800,
        title="工作流最长运行时间",
        description="单次流式生产任务的最长运行秒数，超过后主动取消并返回错误",
    )
    max_research_refine_rounds: int = Field(
        default=2,
        title="最大深度搜索轮次",
        description="初始研究完成后的迭代精炼轮次上限（0 表示不精炼）",
    )
    max_report_refine_rounds: int = Field(
        default=1,
        title="报告精炼轮次",
        description="报告生成后的批判-修改循环次数（0 表示不精炼）",
    )
    enable_report_outline: bool = Field(
        default=True,
        title="报告大纲",
        description="是否在生成正式报告前先生成结构化报告大纲",
    )
    enable_search_filter: bool = Field(
        default=True,
        title="搜索结果过滤",
        description="是否使用 LLM 评估搜索结果质量，过滤低价值内容",
    )
    enable_memory: bool = Field(
        default=False,
        title="历史研究记忆",
        description="可选：是否启用跨任务历史研究记忆；默认关闭，适合专题系列内容复用。",
    )
    enable_script_blueprint: bool = Field(
        default=True,
        title="播客脚本蓝图",
        description="是否先生成节目蓝图，再基于蓝图生成双人对话脚本",
    )
    min_information_gain: float = Field(
        default=0.8,
        title="信息增益阈值",
        description="精炼阶段的信息重复度上限（0-1），超过此值则终止深度搜索（0.8 表示 80% 重复）",
    )
    production_mode: str = Field(
        default="deep",
        title="生产模式",
        description="播客生成模式：quick 快速模式，deep 深度模式",
    )
    search_depth: str = Field(
        default="deep",
        title="搜索深度",
        description="搜索与报告链路深度：quick 快速，deep 深度",
    )
    require_report_outline_confirmation: bool = Field(
        default=False,
        title="报告大纲确认",
        description="是否在生成正式报告前等待用户确认报告大纲",
    )
    report_outline_max_attempts: int = Field(
        default=3,
        title="报告大纲最大生成次数",
        description="用户可触发的大纲生成次数上限",
    )
    podcast_script_target_turns: str = Field(
        default="16-20",
        title="脚本目标轮次",
        description="播客脚本目标对话轮次数，用于约束脚本生成",
    )
    podcast_style: str = Field(
        default="plain",
        title="播客风格",
        description="播客脚本风格：plain 通俗解释，professional 专业分析，news 新闻播报",
    )

    @field_validator("notes_workspace", "audio_output_dir", "intro_bgm_path")
    @classmethod
    def resolve_path(cls, v: str | None) -> str | None:
        """确保路径是绝对路径，如果是相对路径则基于 BACKEND_ROOT 解析。"""
        if v is None:
            return v
        path = Path(v)
        if not path.is_absolute():
            return str(BACKEND_ROOT / path)
        return v

    @field_validator("llm_reasoning_effort")
    @classmethod
    def validate_reasoning_effort(cls, v: str) -> str:
        """限制 DeepSeek thinking mode 的推理强度配置。"""
        if v not in {"high", "max"}:
            raise ValueError("llm_reasoning_effort must be 'high' or 'max'")
        return v

    @field_validator("production_mode")
    @classmethod
    def validate_production_mode(cls, v: str) -> str:
        """限制生产模式配置。"""
        if v not in {"quick", "deep"}:
            raise ValueError("production_mode must be 'quick' or 'deep'")
        return v

    @field_validator("search_depth")
    @classmethod
    def validate_search_depth(cls, v: str) -> str:
        """限制搜索深度配置。"""
        if v not in {"quick", "deep"}:
            raise ValueError("search_depth must be 'quick' or 'deep'")
        return v

    @field_validator("podcast_style")
    @classmethod
    def validate_podcast_style(cls, v: str) -> str:
        """限制播客风格配置。"""
        if v not in {"plain", "professional", "news"}:
            raise ValueError("podcast_style must be 'plain', 'professional' or 'news'")
        return v

    @classmethod
    def from_env(cls, overrides: dict[str, Any] | None = None) -> "Configuration":
        """
        使用环境变量和覆盖项创建配置对象。
        
        Args:
            overrides: 可选的配置覆盖字典。
            
        Returns:
            初始化的配置对象。
        """
        raw_values: dict[str, Any] = {}

        # 基于字段名从环境变量加载值
        for field_name in cls.model_fields.keys():
            env_key = field_name.upper()
            if env_key in os.environ:
                raw_values[field_name] = os.environ[env_key]

        # 兼容旧配置名：FETCH_FULL_PAGE 实际语义是包含搜索后端返回的 raw_content
        if "include_raw_source_content" not in raw_values and "FETCH_FULL_PAGE" in os.environ:
            raw_values["include_raw_source_content"] = os.environ["FETCH_FULL_PAGE"]

        # 处理 NO_PROXY
        no_proxy = os.getenv("NO_PROXY")
        if no_proxy:
            os.environ["NO_PROXY"] = no_proxy
            # 同时设置为小写以兼容
            os.environ["no_proxy"] = no_proxy

        if overrides:
            for key, value in overrides.items():
                if value is not None:
                    raw_values[key] = value

        return cls(**raw_values)

    def build_thinking_body(self, *, enable: bool) -> dict[str, Any] | None:
        """构建 DeepSeek 思考模式的 extra_body 参数。"""
        if enable:
            return {"thinking": {"type": "enabled"}}
        return {"thinking": {"type": "disabled"}}

    def build_reasoning_effort(self, *, enable: bool) -> str | None:
        """在启用思考模式时返回推理强度参数。"""
        if enable:
            return self.llm_reasoning_effort
        return None

    def active_llm_model(self) -> str:
        """返回当前任务实际使用的 LLM 模型。"""
        return self.llm_model_id or "deepseek-v4-flash"
