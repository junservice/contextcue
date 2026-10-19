# Codex collaboration rules — ContextCue

Read `README.md`, `docs/TEAM_WORKFLOW.md`, and `docs/SYSTEM_ARCHITECTURE_PLACEHOLDER.md` before broad changes.

## Scope

- Build a **small demonstrable end-to-end vertical slice first**. Avoid framework proliferation.
- Backend owns `backend/app/*` and API schemas. Frontend owns `frontend/src/*`.
- Any request/response field change must update both `backend/app/schemas.py` and frontend TypeScript types **in the same PR**, plus tests.
- Small commits, clear PR summaries, no force pushes, no direct pushes to main.
- Never change unrelated modules without checking the project design docs.

## Safety and truthful behavior

- Never fabricate camera detections, pixel coordinates, user responses, or successful real model calls.
- Fixture objects are labeled `DEMO_SCENE`, deterministic fallback is labeled `DEMO_RULES`.
- The model may only name an observed object ID; the renderer obtains boxes from validated scene data.
- Unknown / blocked physical capability, ambiguous instruction, or ambiguous object -> confirmation or caregiver assistance; **do not** instruct physically infeasible actions.
- No real student footage, disability profiles, or other sensitive data in source control, logs, screenshots, or external model requests.
- Keep API keys in `backend/.env` and outside version control; never expose them in frontend or Vite environment variables.

## Definition of done

- `uv run pytest`, `uv run ruff check .`, `npm run typecheck` pass.
- If behavior changes, add/update synthetic tests.
- State limitations and whether each feature uses mock data or real Nebius runtime calls.
