import { useId, useRef } from 'react'
import type { Profile } from '../types'
import { canObserve, observationInputs } from '../observation/demoProgress'
import type { DemoObservation, DemoProgressState } from '../observation/types'

export default function DemoObservationControls({ state, profile, onObservation }: {
  state: DemoProgressState; profile: Profile; onObservation: (event: DemoObservation) => void
}) {
  const sequence = useRef(0)
  const sourceId = useId()
  const enabled = canObserve(state, profile)
  const step = state.packing.currentStep
  const objectId = step === 'find_bag' ? 'bag' : 'bottle'
  const inputs = [...observationInputs(step),
    { type: 'observation_uncertain' as const, label: 'Observation uncertain' },
    { type: 'object_lost' as const, label: 'Relevant object lost' },
  ]
  const times = state.orientationTimes
  const elapsed = times.length > 1 ? (times[times.length - 1] - times[0]) / 1000 : 0
  function emit(type: DemoObservation['type']) {
    const id = `${sourceId}:${state.sessionId}:${state.stepEntryId}:${state.evidenceEpoch}:${++sequence.current}`
    onObservation({ type, source: 'DEMO_OBSERVATION', eventId: id, observationId: id,
      sessionId: state.sessionId, stepEntryId: state.stepEntryId, evidenceEpoch: state.evidenceEpoch,
      objectId, observedAtMs: performance.now() })
  }
  return (
    <section className="demo-observation" aria-label="Synthetic observation inputs">
      <h3>DEMO_OBSERVATION · Synthetic observations</h3>
      <p>Each button generates one synthetic observation. No real camera or AI is connected.</p>
      <p>Object detection only establishes location. It does not confirm a user action.</p>
      {enabled && <>
        {(step === 'find_bag' || step === 'find_bottle') &&
          <p>Target location: {(step === 'find_bag' ? state.bagLocated : state.bottleLocated) ? 'located' : 'not located'}</p>}
        {step === 'put_bottle_in_bag' && <>
          <p>Reach evidence: {state.reachedForBottle ? 'recorded' : 'not recorded'} · Near-opening evidence: {state.nearBagOpening ? 'recorded' : 'not recorded'}</p>
          <p>Reaching and proximity only record progress. Repeated bottle-inside-bag observations are required to advance.</p>
        </>}
        <p>Qualifying observations: {times.length} / minimum 3 · Duration: {elapsed.toFixed(1)}s / minimum 1s</p>
        <p>Add qualifying observations about 0.5 seconds apart. A gap over one second restarts accumulation.</p>
        {(step === 'find_bag' || step === 'find_bottle') && <p>Locate the target before adding direction observations.</p>}
        {step === 'check_items' && <p>Add repeated items-confirmed observations to finish the demo. Actual readiness is not verified.</p>}
      </>}
      {!enabled && <p>Automatic progression is unavailable in this state. Caregiver confirmation remains a manual fallback while help is requested.</p>}
      <div className="task-control-buttons">
        {inputs.map((input) => <button key={input.type} type="button" disabled={!enabled}
          onClick={() => emit(input.type)}>{input.label}</button>)}
      </div>
    </section>
  )
}
