# Frontend Codex instructions (`frontend/**`)

Read the root `AGENTS.md` first. Keep React + TypeScript + Vite as the only frontend stack unless a concrete requirement demands otherwise.

- Treat `src/types.ts` as the client mirror of `backend/app/schemas.py`; coordinate changes with the backend owner.
- Only draw object highlights using bounding boxes returned from the observed scene and validated API response. Never guess a location from a natural-language label.
- Clearly label illustrative fixtures as `DEMO_SCENE` and rule-based results as `DEMO_RULES`; only label a response `LIVE_NEBIUS` if the server actually used it.
- Prioritize legibility, large high-contrast cues, short instructions, and non-touch-dependent behavior. Show an assistance/uncertain state instead of a misleading highlight.
- Never put API secrets or identifiable user disability/student data in browser code, local examples, logs, or assets.
- Avoid UI libraries and broad refactors without a demonstrated need.

Verify from `frontend/`:
```powershell
npm ci
npm run typecheck
npm run build
```
