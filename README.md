# ContextCue

**ContextCue** is a prototype cognitive-assistance system for people with co-occurring intellectual and motor disabilities. It combines caregiver-provided functional profiles, observed scene context and task guidance to offer **one grounded, physically feasible cue at a time**. The product vision includes proactive assistance and evidence-based personalization; these are **not yet fully implemented**.

This repository is a **hackathon prototype**, not a validated clinical, accessibility, live camera-perception or autonomous action system.

## Project documents

Start with [Documentation Index](docs/README.md):

- [Project Plan](docs/PROJECT_PLAN.md) — goals, MVP scope, priorities and acceptance criteria
- [System Architecture](docs/SYSTEM_ARCHITECTURE.md) — current vs target modules, API, state and safety boundaries
- [Backend Implementation Plan](backend/IMPLEMENTATION_PLAN.md) — dependency-ordered Backend phases, progress and next task
- [Automatic-door scenario](docs/scenarios/automatic-door.md) — primary MVP walkthrough and evidence criteria
- [Team Workflow](docs/TEAM_WORKFLOW.md) — two-person, main-first Git coordination
- [Frontend manual QA checklist](docs/qa/frontend-manual-checklist.md) — planned checks, **not yet executed**

For coding agents, see [AGENTS.md](AGENTS.md) and the backend/frontend scoped instructions.

## Current implementation (2026-10-21 main snapshot)

| Component | Actual state |
|---|---|
| Frontend | React/Vite; synthetic A/B capability profiles, preferences, local five-step packing-bag demo (help levels 0–4) |
| Backend | FastAPI `GET /api/health` and `POST /api/plan`; guarded single-cue planning |
| Inference | Explicit `DEMO_RULES` mode and optional `LIVE_NEBIUS` integration code; real endpoint/model success **not verified** |
| Scenes | Fixed `DEMO_SCENE` objects and SVG; no working camera/object detector |
| Task lifecycle | Packing demo has a frontend-only state machine; **no backend automatic-door Task Engine yet** |
| Missing integrations | Live perception, ASR, audio TTS, task evidence validation and durable memory |

The **automatic door** is the primary target end-to-end scenario. The packing-bag demo remains a **separate frontend-only UI/state-machine example**, not an AI/backend-connected task.

## Run locally (Windows PowerShell)

Prerequisites: Git, Node.js 24 LTS, Python 3.12 and [uv](https://docs.astral.sh/uv/).

**Terminal A — Backend**
```powershell
cd backend
uv sync --group dev
# On first use, copy the example configuration; never commit .env
Copy-Item .env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

**Terminal B — Frontend**
```powershell
cd frontend
npm ci
npm run dev
```

Open http://localhost:5173 for the UI and http://localhost:8000/docs for FastAPI docs. Start without credentials in `PLANNER_MODE=demo`. Live inference requires a **valid** Nebius API key, accessible NVIDIA model ID and `PLANNER_MODE=live` in the ignored `backend/.env`. Do **not** assume the example model ID is available. A failed live call must not be silently presented as demo inference.

**Checks**
```powershell
# from backend/
uv run pytest
uv run ruff check .

# from frontend/
npm run typecheck
npm run build
```

GitHub CI checks Python tests/lint and frontend typecheck/build. CI success does **not** prove a real Nebius call, camera recognition, browser/accessibility QA, or observed action completion.

## Existing API and safety contract

`POST /api/plan` takes `transcript`, `user_profile` and `scene_objects`. It returns a validated cue or confirmation/assistance status; `bbox` must always originate in the supplied observations, **never LLM-generated coordinates**. `backend/app/schemas.py` is the implemented Python contract; `frontend/src/types.ts` mirrors it.

Use only synthetic profiles, staged scenes and consenting adults for demonstrations. Do not collect or transmit identifiable student/disability information or real school footage without appropriate authorization. Unobserved actions are **unknown**, not completed. This software does not establish clinical efficacy.

## Development and collaboration

Two contributors work main-first: routine verified work can be committed to `main`, while risky/cross-cutting changes may use a feature branch. Coordinate shared API/schema changes before editing both sides. See [Team Workflow](docs/TEAM_WORKFLOW.md) rather than outdated repository-bootstrapping instructions.

Hackathon rules and submission details: https://nebiusglobalaihackathon.devpost.com/rules . Validate actual Nebius + NVIDIA model use and current event rules before claiming compliance.
