# ContextCue — Codex repository instructions

## Goal and sources of truth
Build a small, testable cognitive-assistance MVP: synthetic functional profiles + scene observations + natural-language instruction -> one physically feasible, grounded cue or a clear request for assistance.

Read `README.md` and `docs/TEAM_WORKFLOW.md` at the start of a new task. Read relevant source files before editing. The current `docs/SYSTEM_ARCHITECTURE_PLACEHOLDER.md` is only a placeholder, not a complete specification; do not infer missing requirements from it. If `docs/IDEA_NOTE.md` or `docs/SYSTEM_ARCHITECTURE.md` are added later, use them for product/architecture decisions. Prefer focused reads over loading unrelated files.

## 2-person collaboration — main-first workflow
- The **default working branch is `main`**. For this short hackathon, small verified changes may be committed directly to `main`; feature branches and pull requests are optional, not mandatory.
- Use a separate feature branch for **high-risk, experimental, long-running, or cross-cutting** work that could destabilize the working demo.
- The backend owner normally changes `backend/**`; the frontend/perception owner normally changes `frontend/**`. Ownership is for coordination, not exclusive permission.
- Before editing, inspect `git status` and current branch; when the working tree is clean, sync `main` with `git pull --ff-only origin main`. If there are uncommitted changes or the pull cannot fast-forward, stop and resolve safely rather than discarding work.
- Scope each task narrowly. Avoid large refactors, unrequested dependency upgrades, or unrelated formatting while implementing an MVP feature.
- If changing the shared API, coordinate first and update `backend/app/schemas.py`, `frontend/src/types.ts`, callers, and contract tests consistently. Do not edit the same files concurrently without coordination.
- Run relevant tests before suggesting a commit/push. **Codex must not commit, push, reset, force-push, switch branches, or resolve a teammate's conflicts without the user's explicit instruction.** Never force-push `main`.
- If a push is rejected because `main` moved, do not force it. Inspect the situation, incorporate the remote changes safely, then rerun relevant checks.

## Non-negotiable product constraints
- Use synthetic user profiles, staged scenes, and consenting adult demonstrations. Never commit or transmit real student footage, disability records, private identifiers, or secrets.
- API keys are server-side only in ignored `backend/.env`; never put them in `frontend/`, logs, commits, or PR descriptions.
- A language model may select **only an observed object ID**, never invent a bounding box or assert an unobserved action completed. Visual coordinates must originate in validated observations.
- Unknown/blocked motor abilities, ambiguous objects or addressees, refusal, or unsafe actions must lead to confirmation, assistance, or stopping—not a fabricated confident cue.
- Explicitly distinguish `DEMO_SCENE` fixtures, `DEMO_RULES` logic, and verified `LIVE_NEBIUS` calls. Never claim live inference from a mock.
- Give one minimal, accessible cue at a time; do not assume touch or fine motor control is possible.

## Verification and handoff
- Backend changes: from `backend/`, run `uv run pytest` and `uv run ruff check .`.
- Frontend changes: from `frontend/`, run `npm run typecheck` and `npm run build`.
- For a behavior change, add or update synthetic test cases. For an API change, test both sides.
- In the final report say: changed files, observed tests/results, known limitations, and whether inference was demo or live. Never claim tests were run if they were not.
