# Synthetic observation packing flow

This is a DEMO_SCENE / DEMO_RULES simulation driven by DEMO_OBSERVATION inputs.
It does not use a camera, AI, audio, or an API, and does not verify actual action
success or readiness. Button inputs are demonstration controls, not required
physical actions for an end user.

## Evidence and progression

| Current step | Evidence | Result |
| --- | --- | --- |
| find_bag | bag_detected, then repeated user_oriented_to_bag | Advance to find_bottle |
| find_bottle | bottle_detected, then repeated user_oriented_to_bottle | Enter put_bottle_in_bag using existing capability checks |
| put_bottle_in_bag | user_reached_for_bottle | Record progress only |
| put_bottle_in_bag | bottle_near_bag_opening | Record progress only |
| put_bottle_in_bag | Repeated bottle_inside_bag | Advance to check_items |
| check_items | Repeated items_confirmed | Advance to complete / completed |

Every automatic transition requires at least three distinct qualifying observations
spanning at least 1,000 ms. Consecutive qualifying observations may be at most
1,000 ms apart; a larger gap restarts accumulation with the current observation.
Detection and progress-only events never count toward this threshold. Reaching
and proximity are not mandatory prerequisites for inside-bag observations.
These thresholds are demo rules, not validated measures of user performance.

The existing find_bag progression thresholds, location prerequisite, deferred
commit, and manual fallbacks are preserved. Other stages use the same thresholds.
Each event applies to one step only; evidence is never carried into the next step.

## Validation and reset rules

- Ignore events unrelated to the current step before updating evidence or time.
- Expect objectId bag in find_bag and bottle for qualifying events in other steps.
- In put_bottle_in_bag and check_items, uncertainty or loss of either bag or bottle
  resets all evidence for that step. The UI's loss input targets the current object.
- Require DEMO_OBSERVATION source, current session/step/evidence tokens, nonempty
  distinct event and observation IDs, and finite nonnegative increasing times.
- Relevant observation_uncertain or object_lost clears location, repeated evidence,
  progress flags, and pending automatic progression. The step/help level stays unchanged.
- Step or task-status changes clear evidence. Resuming requires fresh observations.
- Restart, profile selection, and profile-setting changes reset the session.
- paused, help_requested, stopped, and completed block automatic observation processing.

## Capability and manual priority

Existing transitions.ts remains authoritative for entering a step. Entering
put_bottle_in_bag with can_extend_arm or can_grasp false or null enters caregiver
help waiting. Observations cannot release that wait. Automatic progression out of
put_bottle_in_bag additionally requires both abilities to be exactly true.
Other capability fields do not add new restrictions to this packing flow.

Manual Next and caregiver confirmation retain their existing eligibility and
behavior. Progress causes remain manual, caregiver, or demo_observation, using
the existing progress-history presentation. A pending automatic commit rechecks
state and tokens. A previously processed pause/help/stop or manual step change
invalidates it; stale manual advances also cannot move the new step again.
This does not claim priority over inputs that arrive after a transition committed.

## Acceptance criteria

| Given | When | Then |
| --- | --- | --- |
| Active find_bag | Only bag_detected repeats | Record location; stay on the step |
| Bag located | Direction observations at 0, 500, 1000 ms | Advance once to find_bottle |
| Active find_bottle | Only bottle_detected repeats | Record location; stay on the step |
| Bottle not located | Direction observations repeat | Do not accumulate qualifying evidence |
| Bottle located | Direction observations meet count and duration | Enter put_bottle_in_bag once |
| Arm or grasp ability false/null | Enter put_bottle_in_bag | Wait for caregiver help; observations cannot advance |
| Active put_bottle_in_bag with both abilities true | Reach/proximity events repeat | Record progress; stay on the step |
| Active put_bottle_in_bag with both abilities true | Inside-bag observations meet threshold | Advance once to check_items |
| Active check_items | items_confirmed meets threshold | Enter complete with completed status |
| Any other step | items_confirmed arrives | Ignore it without changing evidence |
| No accumulated qualifying evidence | One qualifying observation arrives | Stay on the step |
| Two observations less than 1000 ms apart overall | No further observation | Stay on the step even if time passes |
| Accumulated evidence | Next qualifying observation is over 1000 ms later | Restart accumulation from that observation |
| Current-step evidence or pending commit | Relevant uncertainty/object loss arrives first | Clear evidence and pending commit; keep the step |
| Current-step evidence | Unrelated event/object arrives | Leave evidence and last observation time unchanged |
| Any step | Duplicate, stale, or invalid observation arrives | Ignore it |
| paused/help_requested/stopped/completed | Sufficient observations arrive | No automatic progression |
| Pending automatic progression | Pause/help/stop processes first | Cancel pending progression |
| Pending automatic progression | Eligible manual advance processes first | Advance once and invalidate the old commit |
| Automatic advance committed | Old-token manual Next arrives | Do not advance a second step |
| New step or resumed task | Old observations arrive | Reject them; require fresh evidence |
| Full synthetic flow finishes | Review progress history | Every automatic step has demo_observation cause; actual success remains unverified |

## Manual browser procedure (not yet executed)

1. Use the synthetic profile with both arm and grasp abilities true.
2. Locate the bag; add three direction observations about 0.5 seconds apart.
3. Locate the bottle; repeat the direction sequence.
4. Record reach and proximity; verify neither changes the step. Add three
   inside-bag observations about 0.5 seconds apart.
5. Add three items-confirmed observations about 0.5 seconds apart; check completion.
6. Repeat with uncertainty, object loss, pauses, help requests, manual Next, and
   restart during accumulation. Check that new evidence is required.
7. Repeat with false and null arm/grasp abilities; verify caregiver waiting and
   the existing caregiver-confirmation fallback.

## Verification status

- Typecheck: not run for this change; approval required.
- Build: not run for this change; approval required.
- Automated behavior tests: not added or run, as requested.
- Browser behavior: not verified.
- Real camera / AI behavior: not implemented or verified.
