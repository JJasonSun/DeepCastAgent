# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

DeepCast is an automated podcast generation agent. Given a research topic, it performs web research (Tavily + SerpApi hybrid search), generates a Markdown report, converts it into a dual-host dialogue script (Host "苏打" / Guest "茉莉"), and synthesizes audio via MiMo-V2.5-TTS + FFmpeg.

## Build & Run Commands

**Backend** (Python 3.10+, uv-managed):
```bash
cd backend
uv sync                          # Install dependencies
uv run src/main.py               # Start FastAPI server on :8000 (auto-reload)
```

**Frontend** (Node/npm):
```bash
cd frontend
npm install
npm run dev                      # Dev server on http://localhost:5174
npm run build                    # Type-check + production build
```

**Linting**:
```bash
cd backend
uv run ruff check .              # Python linting (ruff)
uv run ruff check --fix .        # Auto-fix
```

**Verification scripts** (no pytest — tests are ad-hoc scripts):
```bash
cd backend
python scripts/verify_llm.py            # LLM connectivity
python scripts/verify_mimo_tts.py       # TTS service
python scripts/verify_ffmpeg.py         # FFmpeg availability
python scripts/verify_search.py         # Search APIs
python scripts/test_agent_workflow.py   # End-to-end workflow
python scripts/test_audio_generator.py  # Audio generation
```

## Architecture

### Data Flow (Plan-and-Solve pipeline)

1. **Planning** (`services/planner.py`): Topic → 3-5 `TodoItem` tasks
2. **Parallel Research** (threads): Each task → hybrid search (`services/search.py`) + summarization (`services/summarizer.py`)
3. **Report** (`services/reporter.py`): DeepSeek model merges summaries into structured Markdown
4. **Script** (`services/script_generator.py`): DeepSeek model → dual-host dialogue JSON (JSON Output)
5. **Audio** (`services/audio_generator.py`): Per-sentence TTS MP3 generation
6. **Synthesis** (`services/audio_synthesizer.py`): FFmpeg concatenation → final `podcast_*.mp3`

### Key Backend Files

- `src/agent.py` — `DeepResearchAgent` orchestrator. Manages the full lifecycle, thread cancellation via `threading.Event`, and bridges sync generators to async SSE via `asyncio.Queue` + `ThreadPoolExecutor`
- `src/agents/` — Multi-agent abstraction layer: `BaseAgent` (ABC), `PlannerAgent`, `ResearcherAgent`, `CriticAgent`, `WriterAgent`, `DirectorAgent` (registry + dispatch)
- `src/main.py` — FastAPI app. Primary endpoint: `POST /research/stream` (SSE). Events: `stage_change`, `todo_list`, `task_status`, `tool_call`, `sources`, `final_report`, `podcast_script`, `audio_progress`, `podcast_ready`, `done`, `cancelled`
- `src/config.py` — `Configuration` (Pydantic BaseModel), loads from `.env` via python-dotenv
- `src/models.py` — `TodoItem`, `SummaryState`, `SummaryStateOutput`
- `src/prompts.py` — All system prompt templates (Chinese)
- `src/services/` — Decoupled service layer (planner, search, summarizer, reporter, script_generator, audio_generator, audio_synthesizer)

### Frontend

- Vue 3 Composition API (`<script setup>`) + TypeScript + Tailwind CSS 4 + DaisyUI 5
- SSE communication via native `fetch` + `ReadableStream` (no Axios) in `src/services/api.ts`
- `App.vue` owns all state and SSE event routing; child views are `SetupView`, `ProductionView`, `PlayerView`

### LLM Model

The backend now uses a single model configuration:
- `LLM_MODEL_ID` (default `deepseek-v4-flash`): active DeepSeek model for the current run.
- `LLM_REASONING_EFFORT` (`high` / `max`): reasoning strength for tasks that enable thinking mode.

## Key Dependencies

- **FFmpeg** — required for audio synthesis. Must be on PATH or set `FFMPEG_PATH` in `.env`
- **Search APIs** — at least one of `TAVILY_API_KEY` or `SERPAPI_API_KEY` required; hybrid mode needs both

## Environment Setup

Copy `backend/env.example` to `backend/.env` and fill in API keys. Key variables: `LLM_API_KEY`, `LLM_BASE_URL`, `TTS_API_KEY`, `TAVILY_API_KEY`, `SERPAPI_API_KEY`, `FFMPEG_PATH` (Windows).

Frontend: `VITE_API_BASE_URL` in `frontend/.env.local` (default `http://localhost:8000`).

## Conventions

- Chinese is used in prompts, comments, logs, and documentation
- Python linting: Ruff with rules E, F, I, UP, D (Google convention), T20 — configured in `pyproject.toml`
- No formal test framework; verification is via scripts in `backend/scripts/`
- Thread safety: `threading.Lock` for shared state, `threading.Event` for cancellation
- The backend uses `sys.path` manipulation in `main.py` for imports within `src/`
