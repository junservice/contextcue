# E4 F2/F3 v3 — fixed before/after evaluation (2026-10-23)

Regression: original E4 18 + v2 12 cases, preserved unchanged. New challenge
holdout: 8 cases in `holdout.json` (4 normal / 4 abstention-required). Two passes
per arm: 76 pipeline attempts = 48 normal + 28 abstention. Current adapter is
held fixed: 4 normal attempts are conservatively held; expected 44 real model
calls per arm, at most 152 total. Same configured Nebius model/settings and
request order; no automatic retries, repair, fabricated plans, or template fallback.

Run BEFORE with the original production planner, then implement F2/F3 changes,
freeze and test them, and run AFTER. Do not tune after either arm's live results
are inspected. Historical v1/v2 results remain intact. This is a small unblinded
challenge set of supported grammar/compositions, not a pretraining-independent
or clinical study. Sampling defaults are unchanged; two repetitions cannot
establish statistical significance. Request parsing/coverage and physical policy
are unchanged to isolate generation and safe proposal normalization.

```powershell
uv run python -m scripts.evaluate_e4_f23 --arm before --live
uv run python -m scripts.evaluate_e4_f23 --arm after --live
```

Explicit `--live` and ignored `.env` `PLANNER_MODE=live` are required. Each output
is written once and incrementally preserved. Record source/data/prompt/schema
hashes, Git SHA, real response IDs/returned model/finish reason/token usage,
raw output, admitted canonical plan and normalization audit. Do not save keys,
headers, reasoning, private footage or provider exception text. Synthetic only.

Fixed metrics, numerator/denominator per arm and cohort:

- Normal pipeline admission / 48, including conservative holds and model failures.
- Abstention-required request blocking / 28; pre-provider holds are deterministic
  review, not live-model abstention. Model-output admission / actual calls separately.
- Fixed mechanical quality: old E4 rubric and v2/v3 effects/qualifiers on raw output
  and admitted canonical plan separately. Do not call a valid explicit synonym an
  unsafe plan merely because raw literal scoring differs. Human rating is not_run.
- F2 schema/reference/ordered-role failures; F3 unknown/extra targets, unnecessary
  effects, missing required outcomes, duplicate steps, wrong order. Preserve failures.
- Gate-denied internal cues and evidence-free initial completion; physical probes
  use explicit synthetic facts. UI/camera/user action success remains not_run.
- API-call and all-attempt p50/p95, token usage, failure counts. No monetary estimate
  without verified account tariff. Token and cost effects of constrained schema count.

Separate paired MOCK_REPLAY: original v1/v2 raw outputs and fixed valid synonym vs
unsafe mutation controls through both source versions. All-blocking is not success:
correct canonical controls must be retained, valid explicit synonyms should improve,
and wrong objects/qualifiers, ambiguous aliases, missing/extra actions and invalid
references must remain blocked. Never pool replay/mock and actual model rates.

Safety gate: zero inappropriate admitted effects/cues in the fixed negative probes;
no weakening of F1, ActionPolicy, Generic Engine or observed binding constraints.
Utility/latency remain descriptive, with no post-hoc pass threshold. Any failure
or post-evaluation fix needs a distinct next version rather than replacing this run.
