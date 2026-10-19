# ContextCue 2-person collaboration

1. **Issue first**: describe one behavior and testable acceptance conditions.
2. `git checkout main && git pull --ff-only`; `git checkout -b feat/<short-topic>`.
3. Split work primarily as (A) backend/planner/guardrails and (B) frontend/perception/cues.
4. Coordinate API contract updates before coding; backend Python and frontend TS types need to match.
5. Never commit `.env`, recordings, real disability profiles, or generated caches.
6. Open a PR; have the other person review; CI must pass. GitHub branch protection should enforce this if your plan supports it.
7. Merge, then delete feature branch; everyone pulls updated main.
8. Keep a stable demo branch or release tag before any risky late-stage features.
9. Label evidence: `DEMO_RULES` (local), `LIVE_NEBIUS` (real Token Factory), and `DEMO_SCENE` (fixture).

## First parallel tickets

- Backend: validate scene grounding + capability constraints; connect Nemotron through Nebius using server-only key; tests.
- Frontend: show one instruction and one cue from POST /api/plan; design large high-contrast highlight; preserve demo-vs-live labels.
- Shared: agree on response states: `cue`, `needs_confirmation`, `needs_assistance`, `unavailable`.
