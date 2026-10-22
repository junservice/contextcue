import { useId, useRef } from 'react'
import type { DemoObservation, DemoProgressState } from '../observation/types'

const inputs: { type: DemoObservation['type']; label: string }[] = [
  { type: 'bag_detected', label: '가방 위치 확보' },
  { type: 'user_oriented_to_bag', label: '가방 쪽을 바라보거나 접근한 관찰 추가' },
  { type: 'observation_uncertain', label: '관찰 불확실' },
  { type: 'object_lost', label: '가방이 화면에서 사라짐' },
]

export default function DemoObservationControls({ state, onObservation }: {
  state: DemoProgressState; onObservation: (event: DemoObservation) => void
}) {
  const sequence = useRef(0)
  const sourceId = useId()
  const enabled = state.packing.currentStep === 'find_bag' && state.packing.taskStatus === 'active'
  const times = state.orientationTimes
  const elapsed = times.length > 1 ? (times[times.length - 1] - times[0]) / 1000 : 0
  function emit(type: DemoObservation['type']) {
    const id = `${sourceId}:${state.sessionId}:${state.stepEntryId}:${state.evidenceEpoch}:${++sequence.current}`
    onObservation({ type, source: 'DEMO_OBSERVATION', eventId: id, observationId: id,
      sessionId: state.sessionId, stepEntryId: state.stepEntryId, evidenceEpoch: state.evidenceEpoch,
      objectId: 'bag', observedAtMs: performance.now() })
  }
  return (
    <section className="demo-observation" aria-label="합성 관찰 입력">
      <h3>DEMO_OBSERVATION · 합성 관찰</h3>
      <p>실제 카메라·AI가 연결되지 않은 이벤트 시뮬레이션입니다. 각 버튼은 합성 관찰 하나를 만듭니다.</p>
      <p>가방 감지는 위치 확보만 뜻하며, 사용자가 가방을 찾았다는 판정이 아닙니다.</p>
      <p>현재 합성 자동 진행은 가방 찾기에서 물병 찾기로 이동하는 구간만 지원합니다. 나머지 단계는 수동으로 진행합니다.</p>
      {enabled && <>
        <p>가방 위치: {state.bagLocated ? '확보됨' : '미확보'}</p>
        <p>사용자 방향 관찰: {times.length} / 최소 3회 · 확인 시간: {elapsed.toFixed(1)}초 / 최소 1초</p>
        <p>가방 위치 확보 후 방향 관찰을 약 0.5초 간격으로 3회 추가해 보세요. 관찰 간격이 1초를 넘으면 다시 누적합니다.</p>
      </>}
      {!enabled && <p>현재 단계 또는 작업 상태에서는 합성 관찰 자동 진행을 사용할 수 없습니다.</p>}
      <div className="task-control-buttons">
        {inputs.map((input) => <button key={input.type} type="button" disabled={!enabled}
          onClick={() => emit(input.type)}>{input.label}</button>)}
      </div>
    </section>
  )
}
