import { canDispatch } from '../packing/transitions'
import type { PackingEvent, PackingState } from '../packing/types'

const actions: { event: PackingEvent; label: string }[] = [
  { event: 'next', label: '다음' },
  { event: 'more_help', label: '도움 더 보기' },
  { event: 'pause', label: '잠시 멈춤' },
  { event: 'continue', label: '계속하기' },
  { event: 'ask_for_help', label: '보호자 도움 요청' },
  { event: 'caregiver_confirm', label: '보호자 확인 후 계속' },
  { event: 'stop', label: '작업 종료' },
  { event: 'restart', label: '처음부터 시작' },
]

export default function TaskControls({ state, onAction }: {
  state: PackingState
  onAction: (event: PackingEvent) => void
}) {
  return (
    <section aria-label="가방 챙기기 조작">
      <h3>조작</h3>
      {actions.map(({ event, label }) => (
        <div key={event}>
          <button type="button" disabled={!canDispatch(state, event)}
            onClick={() => onAction(event)}>{label}</button>
        </div>
      ))}
    </section>
  )
}
