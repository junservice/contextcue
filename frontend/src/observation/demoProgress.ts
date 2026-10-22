import { initialPackingState, transitionPacking } from '../packing/transitions'
import type { DemoProgressAction, DemoProgressState, ObservationToken } from './types'

export function initialDemoProgress(): DemoProgressState {
  return {
    packing: initialPackingState(), sessionId: 0, stepEntryId: 0, evidenceEpoch: 0,
    history: {}, bagLocated: false, orientationTimes: [], seenEventIds: [],
    seenObservationIds: [], lastObservedAt: null, message: '', pendingAuto: false, seenManualIds: [],
  }
}

function clearEvidence(state: DemoProgressState): DemoProgressState {
  return { ...state, evidenceEpoch: state.evidenceEpoch + 1, bagLocated: false,
    orientationTimes: [], seenEventIds: [], seenObservationIds: [], lastObservedAt: null, pendingAuto: false }
}

function sameToken(state: ObservationToken, token: ObservationToken) {
  return state.sessionId === token.sessionId && state.stepEntryId === token.stepEntryId &&
    state.evidenceEpoch === token.evidenceEpoch
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
        message: action.event === 'caregiver_confirm' ? '보호자 확인으로 현재 단계를 수동 진행했습니다.' : '수동 Next로 현재 단계를 진행했습니다. 실제 행동 성공 판정이 아닙니다.' }
    }
    if (packing.taskStatus !== state.packing.taskStatus) {
      return { ...clearEvidence(state), packing, message: '작업 상태가 변경되어 관찰 증거를 초기화했습니다. 재개 후 새 관찰이 필요합니다.' }
    }
    return { ...state, packing }
  }

  if (action.kind === 'commit_auto') {
    if (!state.pendingAuto || !sameToken(state, action.token) ||
      state.packing.currentStep !== 'find_bag' || state.packing.taskStatus !== 'active') return state
    return { ...clearEvidence(state),
      packing: transitionPacking(state.packing, 'next', action.profile),
      stepEntryId: state.stepEntryId + 1,
      history: { ...state.history, find_bag: 'demo_observation' },
      message: 'DEMO_OBSERVATION 조건 충족으로 물병 찾기로 이동했습니다. 실제 행동 성공을 확인한 결과는 아닙니다.' }
  }

  const event = action.observation
  if (state.packing.currentStep !== 'find_bag' || state.packing.taskStatus !== 'active' ||
    !sameToken(state, event) || event.source !== 'DEMO_OBSERVATION' || event.objectId !== 'bag' ||
    !event.eventId || !event.observationId || !Number.isFinite(event.observedAtMs) || event.observedAtMs < 0 ||
    (state.lastObservedAt !== null && event.observedAtMs <= state.lastObservedAt) ||
    state.seenEventIds.includes(event.eventId) || state.seenObservationIds.includes(event.observationId)) return state

  const observed = { ...state, lastObservedAt: event.observedAtMs,
    seenEventIds: [...state.seenEventIds, event.eventId],
    seenObservationIds: [...state.seenObservationIds, event.observationId] }
  if (event.type === 'observation_uncertain' || event.type === 'object_lost') {
    return { ...clearEvidence(observed), message: event.type === 'observation_uncertain'
      ? '관찰이 불확실하여 증거를 초기화했습니다. 현재 단계에서 다시 확인합니다.'
      : '가방이 화면에서 사라져 증거를 초기화했습니다. 도움 수준은 변경하지 않습니다.' }
  }
  if (event.type === 'bag_detected') {
    return { ...observed, bagLocated: true, message: '합성 장면에서 가방 위치를 확보했습니다. 사용자 행동 성공을 뜻하지 않습니다.' }
  }
  if (event.type !== 'user_oriented_to_bag') return state
  if (!state.bagLocated) {
    return { ...observed, message: '가방 위치를 먼저 확보해 주세요. 방향 관찰은 아직 누적하지 않습니다.' }
  }
  const previous = state.orientationTimes
  const gapTooLong = previous.length > 0 && event.observedAtMs - previous[previous.length - 1] > 1000
  const times = [...(gapTooLong ? [] : previous), event.observedAtMs]
  const ready = times.length >= 3 && times[times.length - 1] - times[0] >= 1000
  if (!ready) {
    return { ...observed, orientationTimes: times, message: gapTooLong
      ? '관찰 간격이 1초를 넘어 현재 관찰부터 다시 확인합니다.'
      : '방향 관찰을 확인 중입니다. 횟수와 시간 조건을 모두 충족해야 이동합니다.' }
  }
  // Commit separately so queued Stop/Help/Pause can invalidate the pending advance.
  return { ...observed, orientationTimes: times, pendingAuto: true,
    message: 'DEMO_OBSERVATION 조건을 충족했습니다. 중단·도움 요청 여부를 확인한 뒤 다음 단계로 이동합니다.' }
}
