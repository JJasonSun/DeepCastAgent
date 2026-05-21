"""协调深度研究工作流的编排器。"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Lock, Thread
from typing import Any

from openai import OpenAI

from config import Configuration
from models import SummaryState, SummaryStateOutput, TodoItem
from services.audio_generator import AudioGenerationService
from services.audio_synthesizer import PodcastSynthesisService
from services.memory_manager import MemoryManager
from services.note_manager import NoteManager
from services.planner import PlanningService
from services.reporter import ReportingService
from services.script_generator import ScriptGenerationService
from services.search import dispatch_search, filter_search_results, prepare_research_context
from services.summarizer import SummarizationService
from services.tool_events import ToolCallTracker

logger = logging.getLogger(__name__)


class DeepResearchAgent:
    """基于 OpenAI SDK 协调 TODO 驱动的研究工作流。"""

    def __init__(self, config: Configuration | None = None) -> None:
        """使用配置和共享工具初始化协调器。"""
        self.config = config or Configuration.from_env()

        # OpenAI 客户端（模型在每次请求中指定，客户端可共享）
        self._client = self._init_client()
        self.smart_client = self._client
        self.fast_client = self._client

        # 笔记管理器
        self.note_tool = (
            NoteManager(workspace=self.config.notes_workspace)
            if self.config.enable_notes
            else None
        )

        self._tool_tracker = ToolCallTracker(
            self.config.notes_workspace if self.config.enable_notes else None
        )
        self._tool_event_sink_enabled = False
        self._state_lock = Lock()
        self._cancel_event = Event()  # 取消信号

        # 服务层（直接注入 OpenAI 客户端）
        self.planner = PlanningService(self.smart_client, self.config)
        self.summarizer = SummarizationService(self.fast_client, self.config)
        self.reporting = ReportingService(self.smart_client, self.config)
        self.script_generator = ScriptGenerationService(self.config)
        self.audio_generator = AudioGenerationService(self.config)
        self.podcast_synthesizer = PodcastSynthesisService(self.config)
        self.memory_manager = MemoryManager(self.config, self.fast_client) if config.enable_memory else None

    def cancel(self) -> None:
        """请求取消当前正在执行的研究任务。"""
        logger.info("Cancel requested for research agent")
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        """检查当前任务是否已被取消。"""
        return self._cancel_event.is_set()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def _init_client(self) -> OpenAI:
        """根据配置创建 OpenAI 客户端。"""
        return OpenAI(
            api_key=self.config.llm_api_key,
            base_url=self.config.llm_base_url,
        )

    def _set_tool_event_sink(self, sink: Any) -> None:
        """启用或禁用立即工具事件回调。"""
        self._tool_event_sink_enabled = sink is not None
        self._tool_tracker.set_event_sink(sink)

    def run(self, topic: str) -> SummaryStateOutput:
        """
        执行研究工作流并返回最终报告（同步模式）。

        此方法按顺序执行以下步骤：
        1. 初始化状态和规划任务。
        2. 串行执行每个任务（搜索 + 总结）。
        3. 迭代式深度搜索（信息饱和检测）。
        4. 生成最终报告（含 Self-Refine 精炼）。
        5. 生成播客脚本。
        6. 生成音频文件并合成播客。
        """
        state = SummaryState(research_topic=topic)

        # 检索相关历史记忆
        historical_context = self._retrieve_historical_context(topic)

        state.todo_items = self.planner.plan_todo_list(state, historical_context)
        self._drain_tool_events(state)

        if not state.todo_items:
            logger.info("No TODO items generated; falling back to single task")
            state.todo_items = [self.planner.create_fallback_task(state)]

        for task in state.todo_items:
            for _ in self._execute_task(state, task, emit_stream=False):
                pass

        # 迭代式深度搜索
        self._refine_research(state)

        report = self.reporting.generate_report_with_refine(state)
        self._drain_tool_events(state)
        state.structured_report = report
        state.running_summary = report
        self._persist_final_report(state, report)

        # 保存研究记忆（长期记忆）
        if self.memory_manager:
            self.memory_manager.save_research_memory(state)

        script = self.script_generator.generate_script(state)
        self._drain_tool_events(state)
        state.podcast_script = script

        # 为脚本生成音频
        task_id = f"task_{state.report_note_id}" if state.report_note_id else "task_default"
        audio_files = self.audio_generator.generate_audio(script, task_id)

        # 合成播客
        self.podcast_synthesizer.synthesize_podcast(audio_files, task_id)

        return SummaryStateOutput(
            running_summary=report,
            report_markdown=report,
            todo_items=state.todo_items,
            podcast_script=script,
        )

    def run_stream(self, topic: str) -> Iterator[dict[str, Any]]:
        """
        执行研究工作流并产生增量进度事件（流式模式）。

        此方法使用多线程并行执行研究任务，并通过生成器实时返回进度。
        支持通过 cancel() 方法取消执行。
        """
        # 重置取消状态
        self._cancel_event.clear()

        state = SummaryState(research_topic=topic)
        logger.debug("Starting streaming research: topic=%s", topic)
        yield {"type": "status", "message": "初始化研究流程"}

        # 检索相关历史记忆
        self._historical_context = self._retrieve_historical_context(topic)
        if self._historical_context:
            yield {"type": "log", "message": "📚 [MEMORY] 已加载相关历史研究记忆"}

        if self.is_cancelled():
            yield {"type": "cancelled", "message": "研究任务已取消"}
            return

        # Phase 1: 规划 + 并行研究
        yield from self._stream_research_phase(state)
        if self.is_cancelled():
            yield {"type": "cancelled", "message": "研究任务已取消"}
            return

        # Phase 1.5: 迭代式深度搜索（信息饱和检测）
        yield from self._stream_refine_phase(state)
        if self.is_cancelled():
            yield {"type": "cancelled", "message": "研究任务已取消"}
            return

        # Phase 2: 报告生成（含 Self-Refine 精炼）
        yield from self._stream_report_phase(state)
        if self.is_cancelled():
            yield {"type": "cancelled", "message": "研究任务已取消"}
            return

        # Phase 3: 播客脚本
        script_turns = yield from self._stream_script_phase(state)
        if self.is_cancelled():
            yield {"type": "cancelled", "message": "研究任务已取消"}
            return
        if script_turns == 0:
            yield {"type": "done"}
            return

        # Phase 4: 音频生成 + 合成
        yield from self._stream_audio_phase(state, script_turns)

        yield {"type": "done"}

    # ------------------------------------------------------------------
    # 流式阶段方法
    # ------------------------------------------------------------------

    def _stream_research_phase(self, state: SummaryState) -> Iterator[dict[str, Any]]:
        """Phase 1: 规划任务并行执行搜索 + 总结。"""
        if self.is_cancelled():
            return
        historical_context = getattr(self, "_historical_context", "")
        state.todo_items = self.planner.plan_todo_list(state, historical_context)
        if self.is_cancelled():
            return
        for event in self._drain_tool_events(state, step=0):
            yield event
        if not state.todo_items:
            state.todo_items = [self.planner.create_fallback_task(state)]

        channel_map: dict[int, dict[str, Any]] = {}
        for index, task in enumerate(state.todo_items, start=1):
            token = f"task_{task.id}"
            task.stream_token = token
            channel_map[task.id] = {"step": index, "token": token}

        serialized_tasks = [self._serialize_task(t) for t in state.todo_items]
        logger.info(f"Emitting todo_list event with {len(serialized_tasks)} tasks")
        yield {
            "type": "todo_list",
            "tasks": serialized_tasks,
            "step": 0,
        }

        event_queue: Queue[dict[str, Any]] = Queue()

        def enqueue(
            event: dict[str, Any],
            *,
            task: TodoItem | None = None,
            step_override: int | None = None,
        ) -> None:
            payload = dict(event)
            target_task_id = payload.get("task_id")
            if task is not None:
                target_task_id = task.id
                payload["task_id"] = task.id
            channel = channel_map.get(target_task_id) if target_task_id is not None else None
            if channel:
                payload.setdefault("step", channel["step"])
                payload["stream_token"] = channel["token"]
            if step_override is not None:
                payload["step"] = step_override
            event_queue.put(payload)

        self._set_tool_event_sink(lambda ev: enqueue(ev))

        threads: list[Thread] = []

        def worker(task: TodoItem, step: int) -> None:
            try:
                if self.is_cancelled():
                    enqueue({"type": "__task_done__", "task_id": task.id})
                    return
                enqueue(
                    {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "in_progress",
                        "title": task.title,
                        "intent": task.intent,
                        "query": task.query,
                        "note_id": task.note_id,
                        "note_path": task.note_path,
                    },
                    task=task,
                )
                for event in self._execute_task(state, task, emit_stream=True, step=step):
                    if self.is_cancelled():
                        break
                    enqueue(event, task=task)
            except Exception as exc:
                if self.is_cancelled():
                    logger.info("Task %s cancelled", task.id)
                else:
                    logger.exception("Task execution failed", exc_info=exc)
                enqueue(
                    {
                        "type": "task_status",
                        "task_id": task.id,
                        "status": "failed",
                        "detail": str(exc),
                        "title": task.title,
                        "intent": task.intent,
                        "query": task.query,
                        "note_id": task.note_id,
                        "note_path": task.note_path,
                    },
                    task=task,
                )
            finally:
                enqueue({"type": "__task_done__", "task_id": task.id})

        for task in state.todo_items:
            step = channel_map.get(task.id, {}).get("step", 0)
            thread = Thread(target=worker, args=(task, step), daemon=True)
            threads.append(thread)
            thread.start()

        active_workers = len(state.todo_items)
        finished_workers = 0

        try:
            while finished_workers < active_workers:
                try:
                    event = event_queue.get(timeout=0.5)
                except Empty:
                    if self.is_cancelled():
                        logger.info("Research cancelled during task execution")
                        yield {"type": "cancelled", "message": "研究任务已取消"}
                        return
                    continue
                if event.get("type") == "__task_done__":
                    finished_workers += 1
                    continue
                yield event

            while True:
                try:
                    event = event_queue.get_nowait()
                except Empty:
                    break
                if event.get("type") != "__task_done__":
                    yield event
        finally:
            self._set_tool_event_sink(None)
            for thread in threads:
                thread.join(timeout=1.0)

    def _stream_report_phase(self, state: SummaryState) -> Iterator[dict[str, Any]]:
        """Phase 2: 生成深度研究报告（含 Self-Refine 精炼）。"""
        yield {
            "type": "stage_change",
            "stage": "report",
            "message": "所有研究任务已完成，正在撰写深度研究报告...",
        }
        yield {"type": "log", "message": f"正在调用 {self.config.smart_llm_model} 模型撰写深度报告..."}

        if self.is_cancelled():
            return

        # 使用带精炼的报告生成（流式收集事件）
        report, refine_events = self.reporting.generate_report_with_refine_stream(state)

        if self.is_cancelled():
            return

        # 输出精炼过程中的事件
        for event in refine_events:
            yield event

        final_step = len(state.todo_items) + 1
        for event in self._drain_tool_events(state, step=final_step):
            yield event
        state.structured_report = report
        state.running_summary = report
        yield {"type": "log", "message": f"报告撰写完成，共 {len(report)} 字符"}

        if self.is_cancelled():
            return

        note_event = self._persist_final_report(state, report)
        if note_event:
            yield note_event

        # 保存研究记忆（长期记忆）
        if self.memory_manager:
            memory_id = self.memory_manager.save_research_memory(state)
            if memory_id:
                yield {"type": "log", "message": f"📚 [MEMORY] 研究记忆已保存: {memory_id}"}

        yield {
            "type": "final_report",
            "report": report,
            "note_id": state.report_note_id,
            "note_path": state.report_note_path,
        }

    def _stream_refine_phase(self, state: SummaryState) -> Iterator[dict[str, Any]]:
        """Phase 1.5: 迭代式深度搜索（信息饱和检测）。"""
        max_rounds = self.config.max_research_refine_rounds
        if max_rounds <= 0:
            return

        for round_num in range(max_rounds):
            if self.is_cancelled():
                return

            yield {
                "type": "refine_round",
                "round": round_num + 1,
                "max_rounds": max_rounds,
                "message": f"深度搜索分析第 {round_num + 1}/{max_rounds} 轮...",
            }
            yield {"type": "log", "message": f"[深度搜索] 正在分析已有信息完整性（第 {round_num + 1} 轮）..."}

            should_continue, reason, new_tasks = self.planner.analyze_and_refine(
                state, round_num, max_rounds,
            )

            if not should_continue or not new_tasks:
                yield {
                    "type": "refine_saturation",
                    "round": round_num + 1,
                    "reason": reason,
                    "message": f"信息饱和: {reason}",
                }
                yield {"type": "log", "message": f"[深度搜索] 信息饱和: {reason}"}
                break

            # 将新任务添加到状态中
            yield {"type": "log", "message": f"[深度搜索] 发现信息缺口: {reason}，生成 {len(new_tasks)} 个补充任务"}

            # 为新任务分配 channel 信息
            channel_map: dict[int, dict[str, Any]] = {}
            for index, task in enumerate(new_tasks, start=1):
                token = f"refine_{round_num}_{task.id}"
                task.stream_token = token
                channel_map[task.id] = {"step": len(state.todo_items) + index, "token": token}

            serialized_tasks = [self._serialize_task(t) for t in new_tasks]
            yield {
                "type": "todo_list",
                "tasks": serialized_tasks,
                "step": len(state.todo_items),
                "is_refine": True,
                "round": round_num + 1,
            }

            # 并行执行补充任务（复用 _stream_research_phase 的并行模式）
            event_queue: Queue[dict[str, Any]] = Queue()

            def enqueue(
                event: dict[str, Any],
                *,
                task: TodoItem | None = None,
                step_override: int | None = None,
            ) -> None:
                payload = dict(event)
                target_task_id = payload.get("task_id")
                if task is not None:
                    target_task_id = task.id
                    payload["task_id"] = task.id
                channel = channel_map.get(target_task_id) if target_task_id is not None else None
                if channel:
                    payload.setdefault("step", channel["step"])
                    payload["stream_token"] = channel["token"]
                if step_override is not None:
                    payload["step"] = step_override
                event_queue.put(payload)

            self._set_tool_event_sink(lambda ev: enqueue(ev))

            threads: list[Thread] = []

            def worker(task: TodoItem, step: int) -> None:
                try:
                    if self.is_cancelled():
                        enqueue({"type": "__task_done__", "task_id": task.id})
                        return
                    enqueue(
                        {
                            "type": "task_status",
                            "task_id": task.id,
                            "status": "in_progress",
                            "title": task.title,
                            "intent": task.intent,
                            "query": task.query,
                        },
                        task=task,
                    )
                    for event in self._execute_task(state, task, emit_stream=True, step=step):
                        if self.is_cancelled():
                            break
                        enqueue(event, task=task)
                except Exception as exc:
                    if not self.is_cancelled():
                        logger.exception("Refine task execution failed", exc_info=exc)
                    enqueue(
                        {
                            "type": "task_status",
                            "task_id": task.id,
                            "status": "failed",
                            "detail": str(exc),
                            "title": task.title,
                            "intent": task.intent,
                            "query": task.query,
                        },
                        task=task,
                    )
                finally:
                    enqueue({"type": "__task_done__", "task_id": task.id})

            for task in new_tasks:
                state.todo_items.append(task)
                step = channel_map.get(task.id, {}).get("step", 0)
                thread = Thread(target=worker, args=(task, step), daemon=True)
                threads.append(thread)
                thread.start()

            active_workers = len(new_tasks)
            finished_workers = 0

            try:
                while finished_workers < active_workers:
                    try:
                        event = event_queue.get(timeout=0.5)
                    except Empty:
                        if self.is_cancelled():
                            yield {"type": "cancelled", "message": "研究任务已取消"}
                            return
                        continue
                    if event.get("type") == "__task_done__":
                        finished_workers += 1
                        continue
                    yield event

                while True:
                    try:
                        event = event_queue.get_nowait()
                    except Empty:
                        break
                    if event.get("type") != "__task_done__":
                        yield event
            finally:
                self._set_tool_event_sink(None)
                for thread in threads:
                    thread.join(timeout=1.0)

    def _refine_research(self, state: SummaryState) -> None:
        """同步模式：迭代式深度搜索。"""
        max_rounds = self.config.max_research_refine_rounds
        if max_rounds <= 0:
            return

        for round_num in range(max_rounds):
            if self.is_cancelled():
                return

            logger.info("Refine research round %d/%d", round_num + 1, max_rounds)

            should_continue, reason, new_tasks = self.planner.analyze_and_refine(
                state, round_num, max_rounds,
            )

            if not should_continue or not new_tasks:
                logger.info("Information saturation: %s", reason)
                break

            logger.info("Found information gap: %s, executing %d supplement tasks", reason, len(new_tasks))

            for task in new_tasks:
                state.todo_items.append(task)
                for _ in self._execute_task(state, task, emit_stream=False):
                    pass

    def _stream_script_phase(self, state: SummaryState) -> Iterator[dict[str, Any] | int]:
        """
        Phase 3: 将报告转化为播客脚本。

        Yields 流式事件，最终 return 脚本轮次数 (int)。
        """
        yield {
            "type": "stage_change",
            "stage": "script",
            "message": "正在将研究报告转化为双人对谈播客脚本...",
        }
        yield {"type": "log", "message": f"正在调用 {self.config.fast_llm_model} 模型生成播客脚本..."}
        yield {"type": "log", "message": "脚本策划专家正在创作 Host (苏打) 与 Guest (茉莉) 的对话..."}

        if self.is_cancelled():
            return
        script = self.script_generator.generate_script(state)
        if self.is_cancelled():
            return
        for event in self._drain_tool_events(state):
            yield event
        state.podcast_script = script

        script_turns = len(script) if script else 0
        yield {"type": "log", "message": f"脚本生成完成，共 {script_turns} 轮对话"}
        yield {
            "type": "podcast_script",
            "script": script,
            "turns": script_turns,
        }

        if script_turns == 0:
            yield {"type": "log", "message": "警告：脚本为空，跳过音频生成"}

        return script_turns  # type: ignore[return-value]

    def _stream_audio_phase(self, state: SummaryState, script_turns: int) -> Iterator[dict[str, Any]]:
        """Phase 4: TTS 音频生成 + FFmpeg 合成。"""
        script = state.podcast_script

        yield {
            "type": "stage_change",
            "stage": "audio",
            "message": "正在调用 TTS 语音引擎生成音频...",
        }

        task_id = f"task_{state.report_note_id}" if state.report_note_id else "task_default"

        # 使用队列实现实时流式音频进度
        audio_event_queue: Queue[dict[str, Any]] = Queue()
        audio_result: list = []
        audio_error: list = []
        cancel_audio = Event()

        def audio_progress_callback(current: int, total: int, role: str, preview: str) -> bool:
            """将进度事件放入队列以实现实时更新。"""
            if self.is_cancelled() or cancel_audio.is_set():
                return False
            audio_event_queue.put({
                "type": "audio_progress",
                "current": current,
                "total": total,
                "role": role,
                "preview": preview,
                "message": f"[TTS {current}/{total}] {role} 语音生成成功",
            })
            return True

        def run_audio_generation() -> None:
            """在单独线程中运行音频生成。"""
            try:
                files = self.audio_generator.generate_audio(
                    script, task_id, audio_progress_callback,
                    cancel_event=self._cancel_event,
                )
                audio_result.append(files)
            except Exception as e:
                if not self.is_cancelled():
                    audio_error.append(str(e))
            finally:
                audio_event_queue.put({"type": "_audio_done"})

        yield {"type": "log", "message": f"准备为 {script_turns} 段对话生成语音..."}
        yield {
            "type": "audio_start",
            "total": script_turns,
            "message": f"开始生成 {script_turns} 段语音",
        }

        audio_thread = Thread(target=run_audio_generation, daemon=True)
        audio_thread.start()

        # 实时流式传输进度事件
        while True:
            if self.is_cancelled():
                cancel_audio.set()
                yield {"type": "cancelled", "message": "研究任务已取消"}
                audio_thread.join(timeout=2.0)
                return
            try:
                event = audio_event_queue.get(timeout=0.1)
                if event.get("type") == "_audio_done":
                    break
                yield event
                if event.get("type") == "audio_progress":
                    yield {
                        "type": "log",
                        "message": f"[TTS {event['current']}/{event['total']}] {event['role']} 语音已完成",
                    }
            except Empty:
                continue

        audio_thread.join(timeout=5.0)

        if self.is_cancelled():
            yield {"type": "cancelled", "message": "研究任务已取消"}
            return

        audio_files = audio_result[0] if audio_result else []
        audio_count = len(audio_files) if audio_files else 0

        if audio_error:
            yield {"type": "log", "message": f"音频生成出错: {audio_error[0]}"}

        yield {"type": "log", "message": f"语音生成完成，成功 {audio_count}/{script_turns} 段"}
        yield {
            "type": "audio_generated",
            "files": audio_files,
            "count": audio_count,
        }

        # 合成播客
        yield {
            "type": "stage_change",
            "stage": "synthesis",
            "message": "正在合成完整播客音频文件...",
        }

        if self.is_cancelled():
            yield {"type": "cancelled", "message": "研究任务已取消"}
            return

        yield {"type": "log", "message": "使用 FFmpeg 拼接所有语音片段..."}
        podcast_file = self.podcast_synthesizer.synthesize_podcast(
            audio_files, task_id, cancel_check=self.is_cancelled,
        )
        if podcast_file:
            yield {"type": "podcast_ready", "file": podcast_file}
            yield {"type": "log", "message": f"播客文件生成成功: {podcast_file}"}
        else:
            yield {"type": "log", "message": "播客合成失败，请检查 FFmpeg 配置"}

    # ------------------------------------------------------------------
    # 执行助手
    # ------------------------------------------------------------------
    def _execute_task(
        self,
        state: SummaryState,
        task: TodoItem,
        *,
        emit_stream: bool,
        step: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        对单个任务运行搜索 + 总结逻辑。
        """
        task.status = "in_progress"

        # 透明化：展示搜索查询
        if emit_stream:
            yield {
                "type": "search_query",
                "task_id": task.id,
                "query": task.query,
                "title": task.title,
                "step": step,
            }

        search_result, notices, answer_text, backend = dispatch_search(
            task.query,
            self.config,
            state.research_loop_count,
        )
        task.notices = notices

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
        else:
            self._drain_tool_events(state)

        if notices and emit_stream:
            for notice in notices:
                if notice:
                    yield {
                        "type": "status",
                        "message": notice,
                        "task_id": task.id,
                        "step": step,
                    }

        if not search_result or not search_result.get("results"):
            task.status = "skipped"
            if emit_stream:
                for event in self._drain_tool_events(state, step=step):
                    yield event
                yield {
                    "type": "task_status",
                    "task_id": task.id,
                    "status": "skipped",
                    "title": task.title,
                    "intent": task.intent,
                    "note_id": task.note_id,
                    "note_path": task.note_path,
                    "step": step,
                }
            else:
                self._drain_tool_events(state)
            return
        else:
            if not emit_stream:
                self._drain_tool_events(state)

        # 搜索结果质量评估：过滤低价值内容
        if self.config.enable_search_filter and search_result and search_result.get("results"):
            original_count = len(search_result["results"])
            filtered_results = filter_search_results(
                search_result["results"],
                state.research_topic or task.query,
                self._client,
                self.config,
            )
            if len(filtered_results) < original_count:
                search_result["results"] = filtered_results
                if emit_stream:
                    yield {
                        "type": "log",
                        "message": f"[FILTER] 搜索结果过滤: {original_count} → {len(filtered_results)} 条",
                        "task_id": task.id,
                        "step": step,
                    }

        sources_summary, context = prepare_research_context(
            search_result,
            self.config,
        )

        task.sources_summary = sources_summary

        with self._state_lock:
            state.web_research_results.append(context)
            state.sources_gathered.append(sources_summary)
            state.research_loop_count += 1

        summary_text: str | None = None

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "sources",
                "task_id": task.id,
                "latest_sources": sources_summary,
                "raw_context": context,
                "result_count": len(search_result.get("results", [])),
                "step": step,
                "backend": backend,
                "note_id": task.note_id,
                "note_path": task.note_path,
            }

            summary_stream, summary_getter = self.summarizer.stream_task_summary(state, task, context)
            try:
                for event in self._drain_tool_events(state, step=step):
                    yield event
                for chunk in summary_stream:
                    if chunk:
                        yield {
                            "type": "task_summary_chunk",
                            "task_id": task.id,
                            "content": chunk,
                            "note_id": task.note_id,
                            "step": step,
                        }
                    for event in self._drain_tool_events(state, step=step):
                        yield event
            finally:
                summary_text = summary_getter()
        else:
            summary_text = self.summarizer.summarize_task(state, task, context)
            self._drain_tool_events(state)

        task.summary = summary_text.strip() if summary_text else "暂无可用信息"
        task.status = "completed"

        if emit_stream:
            for event in self._drain_tool_events(state, step=step):
                yield event
            yield {
                "type": "task_status",
                "task_id": task.id,
                "status": "completed",
                "title": task.title,
                "intent": task.intent,
                "summary": task.summary,
                "sources_summary": task.sources_summary,
                "note_id": task.note_id,
                "note_path": task.note_path,
                "step": step,
            }
            # 透明化：提取关键发现展示给用户
            findings = self._extract_key_findings(task.summary)
            if findings:
                yield {
                    "type": "task_findings",
                    "task_id": task.id,
                    "title": task.title,
                    "findings": findings,
                    "step": step,
                }
        else:
            self._drain_tool_events(state)

    @staticmethod
    def _extract_key_findings(summary: str, max_findings: int = 3) -> list[str]:
        """从任务总结中提取关键发现（前 N 个要点）。"""
        if not summary:
            return []

        findings: list[str] = []
        for line in summary.splitlines():
            line = line.strip()
            # 匹配 Markdown 有序/无序列表项
            if line.startswith(("- ", "* ", "+ ")):
                finding = line[2:].strip()
            elif len(line) > 3 and line[0].isdigit() and line[1] in (".", "、", ")"):
                finding = line[2:].strip()
            else:
                continue

            # 去掉 Markdown 格式符号
            finding = finding.replace("**", "").replace("__", "").strip()
            if finding and len(finding) > 5:
                # 截断过长的发现
                if len(finding) > 100:
                    finding = finding[:100] + "..."
                findings.append(finding)

            if len(findings) >= max_findings:
                break

        return findings

    def _retrieve_historical_context(self, topic: str) -> str:
        """检索与当前主题相关的历史记忆，格式化为上下文文本。"""
        if not self.memory_manager:
            return ""

        try:
            memories = self.memory_manager.retrieve_relevant_memories(topic, max_results=3)
            if memories:
                return self.memory_manager.format_memories_for_context(memories)
        except Exception as e:
            logger.warning("Failed to retrieve historical memories: %s", e)

        return ""

    def _drain_tool_events(
        self,
        state: SummaryState,
        *,
        step: int | None = None,
    ) -> list[dict[str, Any]]:
        """共享工具调用跟踪器的代理。"""
        events = self._tool_tracker.drain(state, step=step)
        if self._tool_event_sink_enabled:
            return []
        return events

    def _serialize_task(self, task: TodoItem) -> dict[str, Any]:
        """将任务数据类转换为前端可序列化的字典。"""
        return {
            "id": task.id,
            "title": task.title,
            "intent": task.intent,
            "query": task.query,
            "status": task.status,
            "summary": task.summary,
            "sources_summary": task.sources_summary,
            "note_id": task.note_id,
            "note_path": task.note_path,
            "stream_token": task.stream_token,
        }

    def _persist_final_report(self, state: SummaryState, report: str) -> dict[str, Any] | None:
        if not self.note_tool or not report or not report.strip():
            return None

        note_title = f"研究报告：{state.research_topic}".strip() or "研究报告"
        tags = ["deep_research", "report"]
        content = report.strip()

        note_id = self._find_existing_report_note_id(state)
        response = ""

        if note_id:
            response = self.note_tool.run(
                {
                    "action": "update",
                    "note_id": note_id,
                    "title": note_title,
                    "note_type": "conclusion",
                    "tags": tags,
                    "content": content,
                }
            )
            if response.startswith("笔记不存在"):
                note_id = None

        if not note_id:
            response = self.note_tool.run(
                {
                    "action": "create",
                    "title": note_title,
                    "note_type": "conclusion",
                    "tags": tags,
                    "content": content,
                }
            )
            note_id = self._tool_tracker._extract_note_id(response)

        if not note_id:
            return None

        state.report_note_id = note_id
        if self.config.notes_workspace:
            note_path = Path(self.config.notes_workspace) / f"{note_id}.md"
            state.report_note_path = str(note_path)
        else:
            note_path = None

        payload = {
            "type": "report_note",
            "note_id": note_id,
            "title": note_title,
            "content": content,
        }
        if note_path:
            payload["note_path"] = str(note_path)

        return payload

    def _find_existing_report_note_id(self, state: SummaryState) -> str | None:
        """查找与研究主题相关的现有报告笔记 ID。"""
        if state.report_note_id:
            return state.report_note_id

        for event in reversed(self._tool_tracker.as_dicts()):
            if event.get("tool") != "note":
                continue

            parameters = event.get("parsed_parameters") or {}
            if not isinstance(parameters, dict):
                continue

            action = parameters.get("action")
            if action not in {"create", "update"}:
                continue

            note_type = parameters.get("note_type")
            if note_type != "conclusion":
                title = parameters.get("title")
                if not (isinstance(title, str) and title.startswith("研究报告")):
                    continue

            note_id = parameters.get("note_id")
            if not note_id:
                note_id = self._tool_tracker._extract_note_id(event.get("result", ""))  # type: ignore[attr-defined]

            if note_id:
                return note_id

        return None
