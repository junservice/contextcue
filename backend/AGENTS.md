# Backend Codex instructions (`backend/**`)

Read the root `AGENTS.md` first. Keep FastAPI, the planner, guardrails, and Pydantic schemas small and testable.

- `app/schemas.py` defines the server-side request/response contract. If a public field changes, update `frontend/src/types.ts`, callers, tests, and examples in the same coordinated change.
- Keep deterministic safety and action-feasibility checks separate from the model's proposal. Do not permit LLM output to bypass profile constraints or supply renderable pixel coordinates.
- Reject unknown object IDs, missing detections, blocked/unknown actions, ambiguous targets, and unsafe transitions with a safe state—not a plausible guess.
- Keep Nebius credentials in ignored `.env`; avoid logging prompts or raw sensitive content. Demo mode must function without a key and be clearly labeled.
- Avoid adding services/databases/frameworks unless necessary for the current milestone.

Verify from `backend/`:
```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
```
