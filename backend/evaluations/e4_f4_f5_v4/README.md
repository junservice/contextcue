# E4 F4/F5 v4 — response classification and cue naming (2026-10-23)

Preserve all prior E4/v2/v3 data/results. Freeze this rubric/runner before edits.
Run paired MOCK_REPLAY before/after on all 160 stored actual responses (v1/v2
and both v3 live arms). No API calls in replay; do not call this a live re-eval.
Inputs, raw outputs and observation/policy probes stay identical. Report accepted
plans/normal requests, negative-request blocking, initial false completion and
gate-denied cues. Neither contract classification nor cue wording may admit a
previously rejected plan or lower safety policy.

F4: fixed 13 controls: valid plan; legacy empty object; 4 explicit abstention
reasons; malformed/empty output, missing/unknown reason, extra text, mixed plan
and abstention, duplicate JSON key. Expect exact, distinct classifications.
Untrusted reason claims do not prove a safety hazard or authorize execution.
Legacy `{}` is unspecified no-plan, not proof of intentional/safety refusal.
Transport errors remain sanitized errors; test timeouts/truncation separately.

F5: for each policy-allowed cue, every step target's canonical Korean noun and
all explicit supported qualifiers must appear in the text. Count generic
`대상` and lost qualifiers separately. Unknown labels/qualifiers must yield a
neutral assistance cue, not raw model text or a guessed actionable description.
Test particles, both containment roles, passage naming, unresolved/ambiguous/stale
observations, blocked ability, help level, one-cue/no-Evidence invariants.
Mechanical name coverage is not human comprehension or accessibility efficacy.

After implementation/tests, run one opt-in LIVE_NEBIUS pass on the unchanged
38 v3 cases (24 normal / 14 abstention required), expected 22 API calls and 16
deterministic holds. This validates new schema/provider compatibility and cue
composition; paired replay supplies the exact before/after comparison.
Do not force a live refusal via a modified system prompt and present it as
production abstention quality. If none occurs, real declared-abstention quality
is not measured. Live and mock rates must never be pooled.

```powershell
uv run python -m scripts.evaluate_e4_f45 --arm before --mock
uv run python -m scripts.evaluate_e4_f45 --arm after --mock
uv run python -m scripts.evaluate_e4_f45 --arm after --live
```

New files only; never overwrite an output. Retain source/prompt/schema hashes,
response IDs/model/finish/usage, synthetic raw output and generated cue text.
Human rating, camera, UI exposure and physical completion are `not_run`.
