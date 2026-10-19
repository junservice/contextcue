# ContextCue — two-person Git + Codex workflow (main-first)

## Working agreement
- **Default: one shared `main` branch.** Small, tested work can be committed and pushed directly; a PR or code-review approval is not required.
- Developers work at different times where possible and communicate what they plan to edit. Backend/planner/guardrails mainly use `backend/**`; frontend/perception/cues mainly use `frontend/**`.
- Coordinate changes to shared API files first. `backend/app/schemas.py` is the source of truth and `frontend/src/types.ts` is its mirror.
- Keep changes small, run relevant checks, and do not upload a knowingly broken demo.
- **Use a separate branch only if needed:** substantial architecture changes, risky model/perception experiments, sweeping cross-module edits, or work that must remain incomplete for multiple sessions.
- Do not require PRs or approving reviews merely because a second developer joins. CI should continue running automatically.
- Codex may propose and edit code but **must ask before committing or pushing**; never force-push or discard someone else's work.

## Start of each work session (PowerShell, repository root)
```powershell
git status
git branch --show-current
git pull --ff-only origin main
```
Only pull when on `main` with a clean working tree. If it is not clean, inspect and preserve the changes first. If the pull fails, resolve the cause instead of using reset or force.

## End of each work session
1. Run the relevant tests; check `git status` and review the changed files for secrets or unrelated edits.
2. Commit only the intended files. Examples:
   ```powershell
   git add backend/app/planner.py backend/tests/test_planner.py
   git commit -m "feat: refine planner validation"
   git push origin main
   ```
3. If push is rejected (the other developer pushed first), **do not force push**. Review and safely incorporate remote changes; rerun checks before retrying. Coordinate if both developers edited the same file.
4. Tell the teammate what changed, test outcomes, and any known limitations. After edits made through GitHub web/ChatGPT connection, run `git pull --ff-only origin main` before new local edits.

## When using an optional feature branch
```powershell
git switch main
git pull --ff-only origin main
git switch -c feat/short-topic
```
Test work separately and merge into `main` when ready, preferably through a PR if review helps. No mandatory PR for routine work.

## Shared API / merge hygiene
- Agree on status values before changing them: `cue`, `needs_confirmation`, `needs_assistance`, `unavailable`.
- Update both Python and TypeScript schemas/callers/tests in coordinated changes.
- Never use `git push --force` to solve an ordinary conflict; resolve intentionally.
- Codex instructions live in the root `AGENTS.md` and scoped `backend/AGENTS.md`, `frontend/AGENTS.md`.

## Verification
- Backend: `uv run pytest`, `uv run ruff check .` from `backend/`.
- Frontend: `npm run typecheck`, `npm run build` from `frontend/`.
- GitHub Actions `.github/workflows/ci.yml` runs both on pushes.
- Preserve a known-good release tag or demo branch before risky late-stage work.

## Evidence labels & privacy
- `DEMO_SCENE`: staged/synthetic scene observations.
- `DEMO_RULES`: local deterministic planning without a Nebius call.
- `LIVE_NEBIUS`: a verified Nebius/NVIDIA runtime call.
- Do not commit secrets, real disability profiles, student footage, or raw sensitive data.

## GitHub main protection
- Enable rules blocking **force pushes** and **deletion** of `main` if supported.
- Do **not** enable mandatory PRs, one-review approval, or required status checks for this main-first workflow.
- Reconsider stricter branch protection only if team needs change; confirm the impact on direct pushes first.
