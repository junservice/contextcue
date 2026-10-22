import { initialPackingState, transitionPacking } from '../packing/transitions'
import type { Profile } from '../types'
import type { DemoObservation, DemoProgressAction, DemoProgressState, ObservationToken } from './types'

export function initialDemoProgress(): DemoProgressState {
  return {
    packing: initialPackingState(), sessionId: 0, stepEntryId: 0, evidenceEpoch: 0,
    history: {}, bagLocated: false, bottleLocated: false, reachedForBottle: false,
    nearBagOpening: false, orientationTimes: [], seenEventIds: [],
    seenObservationIds: [], lastObservedAt: null, message: '', pendingAuto: false, seenManualIds: [],
  }
}

function clearEvidence(state: DemoProgressState): DemoProgressState {
  return { ...state, evidenceEpoch: state.evidenceEpoch + 1, bagLocated: false,
    bottleLocated: false, reachedForBottle: false, nearBagOpening: false,
    orientationTimes: [], seenEventIds: [], seenObservationIds: [], lastObservedAt: null, pendingAuto: false }
}

function sameToken(state: ObservationToken, token: ObservationToken) {
  return state.sessionId === token.sessionId && state.stepEntryId === token.stepEntryId &&
    state.evidenceEpoch === token.evidenceEpoch
}

export function canObserve(state: DemoProgressState, profile: Profile): boolean {
  return state.packing.taskStatus === 'active' && state.packing.currentStep !== 'complete' &&
    (state.packing.currentStep !== 'put_bottle_in_bag' ||
      (profile.can_extend_arm === true && profile.can_grasp === true))
}

export function observationInputs(step: DemoProgressState['packing']['currentStep']): {
  type: DemoObservation['type']; label: string
}[] {
  switch (step) {
    case 'find_bag': return [
      { type: 'bag_detected', label: 'Locate bag' },
      { type: 'user_oriented_to_bag', label: 'Add observation toward bag' },
    ]
    case 'find_bottle': return [
      { type: 'bottle_detected', label: 'Locate bottle' },
      { type: 'user_oriented_to_bottle', label: 'Add observation toward bottle' },
    ]
    case 'put_bottle_in_bag': return [
      { type: 'user_reached_for_bottle', label: 'Record reach toward bottle' },
      { type: 'bottle_near_bag_opening', label: 'Record bottle near bag opening' },
      { type: 'bottle_inside_bag', label: 'Add bottle-inside-bag observation' },
    ]
    case 'check_items': return [{ type: 'items_confirmed', label: 'Add items-confirmed observation' }]
    case 'complete': return []
  }
}

// One pure reducer serializes manual and synthetic inputs. Existing transitions stay unchanged.
export function demoProgressReducer(state: DemoProgressState, action: DemoProgressAction): DemoProgressState {
  if (action.kind === 'reset') {
    return { ...initialDemoProgress(), sessionId: state.sessionId + 1,
      stepEntryId: state.stepEntryId + 1, evidenceEpoch: state.evidenceEpoch + 1, message: action.notice }
  }
  if (action.kind === 'manual') {
    // Epoch changes invalidate observations, not a user's current-step fallback.
    if (state.sessionId !== action.token.sessionId || !action.inputId ||
      state.seenManualIds.includes(action.inputId)) return state
    const movesStep = action.event === 'next' || action.event === 'caregiver_confirm'
    if (movesStep && state.stepEntryId !== action.token.stepEntryId) return state
    state = { ...state, seenManualIds: [...state.seenManualIds, action.inputId] }
    const packing = transitionPacking(state.packing, action.event, action.profile)
    if (packing === state.packing) return state
    if (action.event === 'restart') {
      return { ...initialDemoProgress(), sessionId: state.sessionId + 1,
        stepEntryId: state.stepEntryId + 1, evidenceEpoch: state.evidenceEpoch + 1 }
    }
    if (packing.currentStep !== state.packing.currentStep) {
      return { ...clearEvidence(state), packing, stepEntryId: state.stepEntryId + 1,
        history: { ...state.history, [state.packing.currentStep]: action.event === 'caregiver_confirm' ? 'caregiver' : 'manual' },
        message: action.event === 'caregiver_confirm' ? 'Advanced manually after caregiver confirmation.' : 'Advanced with manual Next. Actual action success was not verified.' }
    }
    if (packing.taskStatus !== state.packing.taskStatus) {
      return { ...clearEvidence(state), packing, message: 'Task status changed. Observation evidence was cleared; new observations are required after resuming.' }
    }
    return { ...state, packing }
  }

  if (action.kind === 'commit_auto') {
    if (!state.pendingAuto || !sameToken(state, action.token) || !canObserve(state, action.profile)) return state
    const packing = transitionPacking(state.packing, 'next', action.profile)
    if (packing.currentStep === state.packing.currentStep) return state
    return { ...clearEvidence(state),
      packing,
      stepEntryId: state.stepEntryId + 1,
      history: { ...state.history, [state.packing.currentStep]: 'demo_observation' },
      message: packing.taskStatus === 'completed'
        ? 'DEMO_OBSERVATION conditions met. The demo is complete; actual readiness was not verified.'
        : packing.taskStatus === 'help_requested'
          ? 'DEMO_OBSERVATION conditions met. The next step requires caregiver confirmation; automatic progression is blocked.'
          : 'DEMO_OBSERVATION conditions met. Advanced one demo step; actual action success was not verified.' }
  }

  const event = action.observation
  const step = state.packing.currentStep
  const relevantType = observationInputs(step).some((input) => input.type === event.type) ||
    event.type === 'observation_uncertain' || event.type === 'object_lost'
  const expectedObject = step === 'find_bag' ? 'bag' : 'bottle'
  const relevantObject = event.objectId === expectedObject ||
    ((step === 'put_bottle_in_bag' || step === 'check_items') && event.objectId === 'bag' &&
      (event.type === 'observation_uncertain' || event.type === 'object_lost'))
  if (!canObserve(state, action.profile) || !relevantType || !relevantObject ||
    !sameToken(state, event) || event.source !== 'DEMO_OBSERVATION' ||
    !event.eventId || !event.observationId || !Number.isFinite(event.observedAtMs) || event.observedAtMs < 0 ||
    (state.lastObservedAt !== null && event.observedAtMs <= state.lastObservedAt) ||
    state.seenEventIds.includes(event.eventId) || state.seenObservationIds.includes(event.observationId)) return state

  const observed = { ...state, lastObservedAt: event.observedAtMs,
    seenEventIds: [...state.seenEventIds, event.eventId],
    seenObservationIds: [...state.seenObservationIds, event.observationId] }
  if (event.type === 'observation_uncertain' || event.type === 'object_lost') {
    return { ...clearEvidence(observed), message: event.type === 'observation_uncertain'
      ? 'Observation uncertain. Current-step evidence was cleared; the step is unchanged.'
      : 'Relevant object lost. Current-step evidence was cleared; the step and help level are unchanged.' }
  }
  if (event.type === 'bag_detected') {
    return { ...observed, bagLocated: true, message: 'Bag located in the synthetic scene. This does not confirm user action success.' }
  }
  if (event.type === 'bottle_detected') {
    return { ...observed, bottleLocated: true, message: 'Bottle located in the synthetic scene. This does not confirm user action success.' }
  }
  if (event.type === 'user_reached_for_bottle') {
    return { ...observed, reachedForBottle: true, message: 'Reach evidence recorded. The current step is unchanged.' }
  }
  if (event.type === 'bottle_near_bag_opening') {
    return { ...observed, nearBagOpening: true, message: 'Bottle-near-opening evidence recorded. The current step is unchanged.' }
  }
  if ((step === 'find_bag' && !state.bagLocated) || (step === 'find_bottle' && !state.bottleLocated)) {
    return { ...observed, message: 'Locate the target first. Direction observations are not accumulating yet.' }
  }
  const previous = state.orientationTimes
  const gapTooLong = previous.length > 0 && event.observedAtMs - previous[previous.length - 1] > 1000
  const times = [...(gapTooLong ? [] : previous), event.observedAtMs]
  const ready = times.length >= 3 && times[times.length - 1] - times[0] >= 1000
  if (!ready) {
    return { ...observed, orientationTimes: times, message: gapTooLong
      ? 'The observation gap exceeded one second. Accumulation restarted with this observation.'
      : 'Checking synthetic observations. Both count and duration conditions must be met.' }
  }
  // Commit separately so queued Stop/Help/Pause can invalidate the pending advance.
  return { ...observed, orientationTimes: times, pendingAuto: true,
    message: 'DEMO_OBSERVATION conditions met. Progression is pending a check for stop, help, or pause inputs.' }
}
