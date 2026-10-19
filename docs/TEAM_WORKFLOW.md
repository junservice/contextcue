# ContextCue — two-person Git + Codex workflow

## Phase 0: before the second developer joins
- The repository is public; keep secrets and real student/medical data out of Git.
- Prefer small changes and green CI. Before publishing any change, run checks for touched components.
- Avoid force pushes and deleting `main`. For now, do not require one PR review: the sole maintainer cannot approve their own PR.
- After changing files via the GitHub interface or ChatGPT GitHub connection, sync local checkout with `git pull --ff-only` before continuing.

## Phase 1: both developers active
1. Each developer clones the same repo and runs `uv sync --group dev` in `backend/` and `npm ci` in `frontend/`.
2. Agree on tasks and the request/response schema before parallel coding.
3. Backend/planner/feasibility owner mainly edits `backend/**`; frontend/perception/cue owner mainly edits `frontend/**`. For shared API changes, pair or coordinate a single PR.
4. Start a scoped branch from current `main`:
   ```powershell
   git switch main
   git pull --ff-only
   git switch -c feat/short-topic
   ```
5. Change only the scoped feature, add tests, and run required checks.
6. Push the branch and open a PR with summary, test results, screenshot/demo evidence if UI changes, and risk/limitations. Ask the other person for review.
7. Merge only after CI passes and the reviewer approves. Delete the feature branch, pull the updated `main`, then start the next task.

## Shared contract and merge hygiene
- Source of truth: `backend/app/schemas.py`; mirror: `frontend/src/types.ts`. Keep both consistent.
- Agree on status values before changing them: `cue`, `needs_confirmation`, `needs_assistance`, `unavailable`.
- Do not concurrently modify the same API/schema files in separate branches without coordination.
- Never use `git push --force` to solve an ordinary conflict; resolve the merge/rebase intentionally.
- Codex instructions live in root and scoped `AGENTS.md` files. Codex may edit code but does not decide to push or merge on its own.

## Required verification
- Backend: `uv run pytest`, `uv run ruff check .` from `backend/`.
- Frontend: `npm run typecheck`, `npm run build` from `frontend/`.
- GitHub Actions `.github/workflows/ci.yml` runs both.
- Keep a stable release tag or demo branch before risky late-stage experiments.

## Evidence labels
- `DEMO_SCENE`: staged/synthetic scene observations.
- `DEMO_RULES`: local deterministic planning without a Nebius model call.
- `LIVE_NEBIUS`: verified runtime call to Nebius/NVIDIA model.

## Repo rules migration
- While solo: block force-push/deletion of `main`; do not enable a required approving review.
- When both accounts have access: require PRs, successful `backend` and `frontend` status checks, and one approving review. Avoid admin bypass in normal work; verify CI on a test PR before enforcing status checks.
