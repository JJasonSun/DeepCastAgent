# AGENTS.md

## Quick Start

Backend (Python 3.10+, uv-managed):
```bash
cd backend && uv sync
uv run src/main.py               # FastAPI on :8000, auto-reload
```

Frontend (Node/npm):
```bash
cd frontend && npm install
npm run dev                      # Vite on http://localhost:5174
npm run build                    # vue-tsc --noEmit && vite build
```

Lint:
```bash
cd backend && uv run ruff check .        # check
cd backend && uv run ruff check --fix .  # auto-fix
```

## Testing

No pytest. Verification is via ad-hoc scripts in `backend/scripts/`:
```bash
cd backend
uv run python scripts/verify_llm.py           # LLM connectivity
uv run python scripts/verify_mimo_tts.py      # TTS service
uv run python scripts/verify_ffmpeg.py        # FFmpeg availability
uv run python scripts/verify_search.py        # Search APIs
uv run python scripts/test_agent_workflow.py  # End-to-end workflow
uv run python scripts/test_audio_generator.py # Audio generation
```
Additional offline guards: `verify_llm_empty_retry.py`, `verify_intro_bgm.py`, `verify_script_json_schema.py`, `verify_report_failure_guard.py`, `verify_report_preamble_cleanup.py`, `verify_script_failure_guard.py`, `verify_production_modes.py`, `verify_style_and_tts_controls.py`.

## Environment

Copy `backend/env.example` → `backend/.env`. The `.env` is loaded from `backend/` root (not project root) by `main.py` via python-dotenv.

Required keys: `LLM_API_KEY`, `LLM_BASE_URL`, `TTS_API_KEY`. At least one of `TAVILY_API_KEY` or `SERPAPI_API_KEY`; hybrid mode needs both. `FFMPEG_PATH` only needed on Windows.

Frontend: `VITE_API_BASE_URL` in `frontend/.env.local` (default `http://localhost:8000`).

## Architecture

Pipeline: Topic → PlannerAgent (TodoItem tasks) → ResearcherAgent (parallel hybrid search + summarization, iterative refinement) → WriterAgent (report outline + draft) → CriticAgent (quality eval) → WriterAgent (revision) → WriterAgent (podcast blueprint + dual-host dialogue JSON) → AudioGenerator (MiMo TTS per-sentence) → AudioSynthesizer (FFmpeg concat) → `podcast_*.mp3`.

Key entry points:
- `backend/src/main.py` — FastAPI app. Primary endpoint: `POST /research/stream` (SSE). Health: `GET /api/health`.
- `backend/src/agent.py` — `DeepResearchAgent` orchestrator. Bridges sync generators to async SSE via `asyncio.Queue` + `ThreadPoolExecutor`.
- `backend/src/agents/director.py` — `DirectorAgent` registry + dispatch for all agents.
- `backend/src/config.py` — `Configuration` (Pydantic). Loads from env vars (field name uppercased). Two presets: `quick` (deepseek-v4-flash, no refinement) and `deep` (deepseek-v4-pro, max reasoning, full pipeline).
- `backend/src/prompts.py` — All system prompt templates (Chinese).

Frontend: Vue 3 Composition API (`<script setup>`) + TypeScript + Tailwind CSS 4 + DaisyUI 5. SSE via native `fetch` + `ReadableStream` (no Axios) in `src/services/api.ts`. `App.vue` owns all state; child views: `SetupView`, `ProductionView`, `PlayerView`.

## Conventions

- Chinese is used in prompts, comments, logs, and documentation.
- Ruff rules: E, F, I, UP, D (Google convention), T20. Configured in `pyproject.toml`. Key ignores: D100-D107 (docstrings), E501 (line length), D400/D415 (Chinese period detection). `scripts/*` ignores T201 (print). `main.py` uses `# ruff: noqa: E402` at top due to sys.path insert before imports.
- `main.py` does `sys.path.insert(0, ...)` to add `src/` dir before importing sibling modules. This is required for both direct run and uvicorn.
- Thread safety: `threading.Lock` for shared state, `threading.Event` for cancellation.
- LLM defaults: `deepseek-v4-flash` (quick) / `deepseek-v4-pro` (deep). Reasoning effort: `high` or `max` for DeepSeek thinking mode.
- TTS: MiMo-V2.5-TTS with director mode + VoiceDesign. Preset voices: Host "苏打", Guest "茉莉".
