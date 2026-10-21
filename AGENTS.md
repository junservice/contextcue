# ContextCue — Codex repository instructions

## Canonical project references

Read `README.md` and `docs/TEAM_WORKFLOW.md` for every new task. Read relevant sections of `docs/PROJECT_PLAN.md` for product scope and `docs/SYSTEM_ARCHITECTURE.md` for module boundaries, implemented vs target features and API impact. Read `docs/scenarios/automatic-door.md` before automatic-door behavior changes.

Documentation index: `docs/README.md`. Avoid copying the entire plans into agent prompts. The plans describe **goals as well as implemented features**; never equate the two. The real Python/TypeScript schemas and tests reflect current contracts; coordinate any change to align them with plans. Prefer focused reads and source inspection before edits.

## 2-person collaboration — main-first workflow

- The default working branch is `main`. Small, verified changes may be committed directly; PRs are optional, not mandatory.
- Use a separate feature branch for high-risk, experimental, long-running or cross-cutting work that could destabilize the demo.
- Backend owner normally changes `backend/**`; frontend owner normally changes `frontend/**`. Ownership is for coordination, not exclusive permission.
- Before editing, inspect `git status` and branch. With a clean tree, sync `main` using `git pull --ff-only origin main`. If unsafe, stop and resolve without discarding others' work.
- Keep changes narrowly scoped; avoid unrelated refactors, dependencies or formatting.
- Shared API changes require coordination and consistent updates to `backend/app/schemas.py`, `frontend/src/types.ts`, callers and tests.
- Run relevant checks before suggesting commit/push. **Codex must not commit, push, reset, force-push, switch branches or resolve teammate conflicts without explicit user instruction.** Never force-push `main`.
- For rejected pushes, inspect upstream, incorporate changes safely, rerun checks, never force.

## Non-negotiable product constraints

- Use synthetic profiles, staged scenes and consenting adult demos. Never commit or transmit real student footage, identifiable disability records, private identifiers or secrets.
- API keys belong only in ignored server-side `backend/.env`; never expose them in frontend, logs, commits or PR descriptions.
- The AI may select only observed object IDs. Bounding boxes come from validated observations, not a language model.
- Never infer action success from a displayed cue, button press in demo UI or lack of user response.
- Block/unknown abilities, ambiguous objects or addressees, refusal or unsafe actions require confirmation, assistance or stop—not fabricated cues.
- Do not assume `can_extend_arm=true` proves actual reachability or accurate button pressing. Treat each relevant ability and real-world reachability independently.
- Distinguish `DEMO_SCENE` fixtures, `DEMO_RULES` logic and **verified** `LIVE_NEBIUS` calls. Never claim mocks are live.
- Offer one accessible minimal cue at a time, respecting refusal and motor limitations.

## Verification and handoff

- Backend: from `backend/`, run `uv run pytest` and `uv run ruff check .`.
- Frontend: from `frontend/`, run `npm run typecheck` and `npm run build`.
- Add synthetic tests for behavior changes; update both sides for API changes.
- Report changed files, observed check results, known limitations and whether inference was demo or live. Never claim unexecuted tests passed.
