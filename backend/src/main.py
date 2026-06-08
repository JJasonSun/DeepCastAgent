"""通过 HTTP 暴露 DeepResearchAgent 的 FastAPI 入口点。"""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import concurrent.futures
import glob
import json
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

# Ensure src directory is in sys.path for module imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Load .env file from backend root
from dotenv import load_dotenv

_backend_root = Path(__file__).resolve().parent.parent
_env_path = _backend_root / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, Field

from agent import DeepResearchAgent
from config import Configuration

# 添加控制台日志处理程序
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <4}</level> | <cyan>using_function:{function}</cyan> | <cyan>{file}:{line}</cyan> | <level>{message}</level>",
    colorize=True,
)


class ResearchRequest(BaseModel):
    """触发研究运行的负载。"""

    topic: str = Field(..., description="用户提供的研究主题")
    llm_model_id: Literal["deepseek-v4-flash", "deepseek-v4-pro"] | None = Field(
        default=None,
        description="本次任务使用的 DeepSeek 模型",
    )
    llm_reasoning_effort: Literal["high", "max"] | None = Field(
        default=None,
        description="关键任务的推理强度",
    )

class PodcastScript(BaseModel):
    """播客脚本内容模型。"""
    script: str = Field(..., description="生成的播客脚本内容")


class ResearchResponse(BaseModel):
    """包含生成报告和结构化任务的 HTTP 响应。"""

    report_markdown: str = Field(
        ..., description="Markdown 格式的研究报告，包含各个部分"
    )
    todo_items: list[dict[str, Any]] = Field(
        default_factory=list,
        description="带有摘要和来源的结构化待办事项",
    )
    podcast_script: PodcastScript | None = Field(
        default=None,
        description="生成的播客脚本内容",
    )
    podcast_blueprint: dict[str, Any] | None = Field(
        default=None,
        description="生成的播客节目蓝图",
    )


class HealthCheckItem(BaseModel):
    """首页运行前健康检查条目。"""

    id: Literal["backend", "llm", "tts", "search", "ffmpeg", "audio_output"]
    label: str
    status: Literal["ok", "warning", "error"]
    message: str


class HealthCheckResponse(BaseModel):
    """首页运行前健康检查结果。"""

    status: Literal["ok", "warning", "error"]
    blocking: bool
    checks: list[HealthCheckItem]


def _mask_secret(value: str | None, visible: int = 4) -> str:
    """在保持前导和尾随字符的同时，掩盖敏感令牌。"""
    if not value:
        return "unset"

    if len(value) <= visible * 2:
        return "*" * len(value)

    return f"{value[:visible]}...{value[-visible:]}"


def _build_config(payload: ResearchRequest | None = None) -> Configuration:
    overrides: dict[str, Any] = {}
    if payload is not None:
        if payload.llm_model_id:
            overrides["llm_model_id"] = payload.llm_model_id
        if payload.llm_reasoning_effort:
            overrides["llm_reasoning_effort"] = payload.llm_reasoning_effort
    return Configuration.from_env(overrides)


def _check_ffmpeg(config: Configuration) -> HealthCheckItem:
    configured_path = config.ffmpeg_path

    if configured_path:
        path = Path(configured_path)
        if not path.is_absolute():
            return HealthCheckItem(
                id="ffmpeg",
                label="FFmpeg",
                status="error",
                message="FFMPEG_PATH 必须配置为绝对路径",
            )
        if not path.exists():
            return HealthCheckItem(
                id="ffmpeg",
                label="FFmpeg",
                status="error",
                message=f"未找到 FFmpeg 可执行文件：{configured_path}",
            )
        if not os.access(path, os.X_OK):
            return HealthCheckItem(
                id="ffmpeg",
                label="FFmpeg",
                status="error",
                message=f"FFmpeg 路径不可执行：{configured_path}",
            )
        return HealthCheckItem(
            id="ffmpeg",
            label="FFmpeg",
            status="ok",
            message=f"FFmpeg 可用：{configured_path}",
        )

    detected_path = shutil.which("ffmpeg")
    if not detected_path:
        return HealthCheckItem(
            id="ffmpeg",
            label="FFmpeg",
            status="error",
            message="未配置 FFMPEG_PATH，系统 PATH 中也未找到 ffmpeg",
        )

    return HealthCheckItem(
        id="ffmpeg",
        label="FFmpeg",
        status="ok",
        message=f"FFmpeg 可用：{detected_path}",
    )


def _check_audio_output(config: Configuration) -> HealthCheckItem:
    output_dir = Path(config.audio_output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".healthcheck_", delete=True):
            pass
    except Exception as exc:
        return HealthCheckItem(
            id="audio_output",
            label="音频输出目录",
            status="error",
            message=f"音频输出目录不可写：{exc}",
        )

    return HealthCheckItem(
        id="audio_output",
        label="音频输出目录",
        status="ok",
        message=f"音频输出目录可写：{output_dir}",
    )


def _build_health_response() -> HealthCheckResponse:
    config = Configuration.from_env()

    checks: list[HealthCheckItem] = [
        HealthCheckItem(
            id="backend",
            label="后端服务",
            status="ok",
            message="后端服务已连接",
        )
    ]

    checks.append(
        HealthCheckItem(
            id="llm",
            label="LLM 配置",
            status="ok" if config.llm_api_key else "error",
            message="LLM_API_KEY 已配置" if config.llm_api_key else "缺少 LLM_API_KEY",
        )
    )
    checks.append(
        HealthCheckItem(
            id="tts",
            label="TTS 配置",
            status="ok" if config.tts_api_key else "error",
            message="TTS_API_KEY 已配置" if config.tts_api_key else "缺少 TTS_API_KEY",
        )
    )

    search_key_count = int(bool(config.tavily_api_key)) + int(bool(config.serpapi_api_key))
    if search_key_count == 2:
        search_status: Literal["ok", "warning", "error"] = "ok"
        search_message = "Tavily 和 SerpApi 均已配置"
    elif search_key_count == 1:
        search_status = "warning"
        search_message = "仅配置了一个搜索后端，可运行但混合搜索能力不完整"
    else:
        search_status = "error"
        search_message = "缺少搜索 API Key：TAVILY_API_KEY 和 SERPAPI_API_KEY 至少需要一个"

    checks.append(
        HealthCheckItem(
            id="search",
            label="搜索配置",
            status=search_status,
            message=search_message,
        )
    )
    checks.append(_check_ffmpeg(config))
    checks.append(_check_audio_output(config))

    if any(item.status == "error" for item in checks):
        status: Literal["ok", "warning", "error"] = "error"
    elif any(item.status == "warning" for item in checks):
        status = "warning"
    else:
        status = "ok"

    return HealthCheckResponse(
        status=status,
        blocking=any(item.status == "error" for item in checks),
        checks=checks,
    )


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    # 当前活跃的研究 agent 引用，用于支持取消操作
    _active_agent: dict[str, DeepResearchAgent | None] = {"current": None}

    # 确保输出目录存在（使用绝对路径，基于 backend 根目录）
    output_dir = os.path.join(str(_backend_root), "output")
    os.makedirs(output_dir, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期管理：启动时记录配置，关闭时清理资源。"""
        config = Configuration.from_env()
        logger.info(
            "DeepResearch configuration loaded: model=%s base_url=%s search_api=%s "
            "max_loops=%s include_raw_source_content=%s strip_thinking=%s api_key=%s",
            config.active_llm_model(),
            config.llm_base_url or "unset",
            config.search_api.value,
            config.max_web_research_loops,
            config.include_raw_source_content,
            config.strip_thinking_tokens,
            _mask_secret(config.llm_api_key),
        )
        yield  # 应用运行中
        # 关闭时清理
        _active_agent["current"] = None

    app = FastAPI(title="DeepCast - 自动播客生成智能体", lifespan=lifespan)

    # 从配置读取 CORS 允许的源，避免生产环境使用通配符
    _startup_config = Configuration.from_env()
    _allowed_origins = [
        origin.strip()
        for origin in _startup_config.cors_origins.split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 挂载静态文件目录，用于访问生成的音频文件
    app.mount("/output", StaticFiles(directory=output_dir), name="output")

    @app.get("/healthz")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health", response_model=HealthCheckResponse)
    def health_detail() -> HealthCheckResponse:
        """返回首页运行前依赖检查结果，不主动探测外部 API。"""
        return _build_health_response()

    @app.get("/api/audio/latest")
    def get_latest_audio() -> dict[str, Any]:
        """获取最新生成的音频文件。"""
        audio_dir = os.path.join(output_dir, "audio")
        if not os.path.exists(audio_dir):
            return {"file": None, "error": "音频目录不存在"}
        
        # 查找所有 podcast_*.mp3 文件
        pattern = os.path.join(audio_dir, "podcast_*.mp3")
        files = glob.glob(pattern)
        
        if not files:
            return {"file": None, "error": "没有找到音频文件"}
        
        # 按修改时间排序，获取最新的
        latest_file = max(files, key=os.path.getmtime)
        filename = os.path.basename(latest_file)
        return {"file": filename, "url": f"/output/audio/{filename}"}

    @app.post("/research", response_model=ResearchResponse)
    def run_research(payload: ResearchRequest) -> ResearchResponse:
        """
        触发同步研究任务。
        
        执行完整的研究流程，并在 HTTP 响应中一次性返回所有结果。
        """
        try:
            config = _build_config(payload)
            agent = DeepResearchAgent(config=config)
            result = agent.run(payload.topic)
        except ValueError as exc:  # Likely due to unsupported configuration
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - defensive guardrail
            raise HTTPException(status_code=500, detail="Research failed") from exc

        todo_payload = [
            {
                "id": item.id,
                "title": item.title,
                "intent": item.intent,
                "query": item.query,
                "status": item.status,
                "summary": item.summary,
                "sources_summary": item.sources_summary,
                "note_id": item.note_id,
                "note_path": item.note_path,
            }
            for item in result.todo_items
        ]

        # 确保 podcast_script 类型正确，Pydantic 模型需要 PodcastScript 实例
        script_content = ""
        if result.podcast_script:
            if isinstance(result.podcast_script, (list, dict)):
                script_content = json.dumps(result.podcast_script, ensure_ascii=False)
            else:
                script_content = str(result.podcast_script)
        
        podcast_resp = PodcastScript(script=script_content)

        return ResearchResponse(
            report_markdown=(result.report_markdown or result.running_summary or ""),
            todo_items=todo_payload,
            podcast_blueprint=result.podcast_blueprint,
            podcast_script=podcast_resp,
        )

    @app.post("/research/cancel")
    async def cancel_research() -> dict[str, str]:
        """
        主动取消当前正在执行的研究任务。
        
        前端可以通过此端点显式通知后端停止处理。
        """
        agent = _active_agent.get("current")
        if agent and not agent.is_cancelled():
            logger.info("Cancel requested via /research/cancel endpoint")
            agent.cancel()
            return {"status": "cancelled", "message": "取消请求已发送"}
        return {"status": "no_task", "message": "当前没有正在运行的任务"}

    @app.post("/research/stream")
    async def stream_research(payload: ResearchRequest, request: Request) -> StreamingResponse:
        """
        触发流式研究任务。
        
        通过 Server-Sent Events (SSE) 实时返回研究进度、日志和部分结果。
        支持客户端断开连接时自动取消后端任务。
        """
        try:
            config = _build_config(payload)
            agent = DeepResearchAgent(config=config)
            _active_agent["current"] = agent  # 注册活跃 agent 以支持取消
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async def event_iterator():
            loop = asyncio.get_running_loop()
            # 用 asyncio.Queue 桥接同步生成器和异步循环
            # 生成器在单一后台线程中完整运行，避免并发调用 next() 破坏生成器状态
            event_queue: asyncio.Queue = asyncio.Queue()
            _SENTINEL = object()  # 生成器结束的哨兵值

            def run_generator():
                """在后台线程中完整运行生成器，将事件逐一推入异步队列。"""
                try:
                    for event in agent.run_stream(payload.topic):
                        if agent.is_cancelled():
                            logger.info("Generator stopped: cancel detected")
                            break
                        loop.call_soon_threadsafe(event_queue.put_nowait, event)
                except Exception as exc:
                    logger.exception("Generator raised exception")
                    loop.call_soon_threadsafe(
                        event_queue.put_nowait,
                        {"type": "error", "detail": f"{exc.__class__.__name__}: {exc}"},
                    )
                finally:
                    loop.call_soon_threadsafe(event_queue.put_nowait, _SENTINEL)

            # 启动断开连接监控任务
            async def monitor_disconnect():
                while True:
                    if await request.is_disconnected():
                        logger.info("Client disconnected detected by monitor")
                        agent.cancel()
                        return
                    await asyncio.sleep(0.5)

            monitor_task = asyncio.create_task(monitor_disconnect())
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            loop.run_in_executor(executor, run_generator)
            heartbeat_interval = max(config.sse_heartbeat_interval, 5)
            last_heartbeat_at = loop.time()
            started_at = loop.time()

            try:
                while True:
                    try:
                        # 带超时等待，以便能及时响应取消
                        item = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # 超时时检查是否已取消（用于客户端断开但生成器还未感知的情况）
                        if agent.is_cancelled():
                            logger.info("✅ 本次任务已取消（超时检测）")
                            yield 'data: {"type": "cancelled", "message": "研究任务已被用户取消"}\n\n'
                            break
                        now = loop.time()
                        if now - started_at >= config.workflow_max_seconds:
                            agent.cancel()
                            error = {
                                "type": "error",
                                "detail": f"工作流超过最长运行时间 {config.workflow_max_seconds} 秒，已自动取消",
                            }
                            yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
                            break
                        if now - last_heartbeat_at >= heartbeat_interval:
                            heartbeat = {
                                "type": "heartbeat",
                                "message": "后端仍在处理，请保持页面打开",
                            }
                            yield f"data: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
                            last_heartbeat_at = now
                        continue

                    # 哨兵：生成器已结束
                    if item is _SENTINEL:
                        break

                    event = item
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    last_heartbeat_at = loop.time()

                    if event.get("type") in ("done", "cancelled", "error"):
                        break
            finally:
                # 确保取消信号被设置 —— 这是取消机制的核心：
                # 前端 abort SSE 后 monitor_task 可能还未检测到断连就被 cancel，
                # 而 /research/cancel API 到达时 _active_agent 可能已被置 None。
                # 因此必须在此处显式调用 cancel() 确保后台线程能感知取消。
                agent.cancel()
                monitor_task.cancel()
                try:
                    await monitor_task
                except asyncio.CancelledError:
                    pass
                executor.shutdown(wait=False)
                _active_agent["current"] = None

        return StreamingResponse(
            event_iterator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    _config = Configuration.from_env()
    uvicorn.run(
        "main:app",
        host=_config.host,
        port=_config.port,
        reload=True,
        log_level=_config.log_level.lower(),
    )
