# ContextCue Starter — two-person hackathon scaffold

A minimal React + FastAPI vertical slice for ContextCue. **This is a development scaffold, not a finished accessibility or object-detection system.** It uses synthetic profiles and an illustrative SVG scene. Live inference uses NVIDIA Nemotron via Nebius Token Factory when a private API key is configured.

## Prerequisites

- Git, VS Code, Node.js 24 LTS (or a supported Vite Node version)
- Python 3.12, [uv](https://docs.astral.sh/uv/)
- An optional Nebius Token Factory API key for *live* inference

## First run (Windows PowerShell, two terminals)

Terminal A:

```powershell
cd backend
uv sync --group dev
Copy-Item .env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

Terminal B:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 . The API is at http://localhost:8000/docs . With `NEBIUS_API_KEY` empty, the backend uses a visibly labeled **DEMO_RULES** mode. To make actual calls, put your key in `backend/.env`, then set `PLANNER_MODE=live`. Do not commit `.env`.

In another backend terminal, run tests:

```powershell
cd backend
uv run pytest
uv run ruff check .
```

For frontend type checking:

```powershell
cd frontend
npm run typecheck
```

## Git / team setup

1. Create a **public** GitHub repo with no auto-generated files if you plan to upload this starter as the first commit. Invite your collaborator with write access.
2. Extract this archive; from the extracted root run `git init -b main`, `git add .`, `git commit -m "chore: bootstrap ContextCue"`, `git remote add origin <YOUR_REPO_URL>`, `git push -u origin main`. If you already initialized README / LICENSE on GitHub, clone that repository first, copy the starter content into it, and commit instead; **do not use `git push --force`.**
3. Run `npm install` once in `frontend`, commit the resulting `package-lock.json` so both teammates can use `npm ci` afterward.
4. Run `uv lock` once in `backend`, commit `uv.lock` so both teammates use consistent dependencies.
5. Enable GitHub branch protection (pull requests and, if available under your plan, 1 review + CI). Work on `feat/your-change` branches, not directly on `main`.
6. Copy your full IDEA_NOTE.md and SYSTEM_ARCHITECTURE.md into `docs/` and reconcile API changes in Pull Requests.

## Architecture

- `frontend/src/App.tsx`: synthetic user profile, spoken-instruction *text* input, illustrative scene, bbox cue rendering
- `backend/app/schemas.py`: the shared request/response contract (kept mirrored via TypeScript definitions)
- `backend/app/planner.py`: local guardrails, demonstration rule planner, optional live Nebius model call
- `backend/app/main.py`: FastAPI routes and CORS
- `backend/tests/`: tests for feasibility and grounding safeguards
- `AGENTS.md`: Codex agent instructions; `docs/TEAM_WORKFLOW.md`: collaboration policy

### API

`POST /api/plan` accepts a synthetic user profile, instruction text, and detected scene objects. It returns a validated single cue or a confirmation/assistance status. **Bounding boxes always come from the supplied scene observations, not from an LLM response.** The demo's object bounding boxes are fixtures, not actual detections.

### Next implementation steps

- Replace the fake SVG scene and static `scene_objects` with a real image, detector, and trustworthy object locations.
- Add Korean ASR and audio TTS, accessible cue delivery, lifecycle and state machine.
- Add scenario tests for addressee uncertainty, ambiguous objects, and rejection/stop behavior.
- Evaluate the exact Nemotron model, its runtime availability, JSON behavior, and costs using your Nebius account.

## Safety & hackathon scope

Use only synthetic profiles, staged scenes, and consenting adult demo actors. Do not collect or transmit identifiable disability, student, or school footage without appropriate authorization. No claim of clinical efficacy is made.

**Competition**: Verify the final submission instructions at https://nebiusglobalaihackathon.devpost.com/rules . A submitted demo must show *actual* Nebius + NVIDIA model use: DEMO_RULES mode alone does not meet that requirement.
