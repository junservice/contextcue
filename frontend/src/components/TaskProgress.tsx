import { stepOrder } from '../packing/steps'
import type { PackingState, PackingStep } from '../packing/types'
import type { ProgressCause } from '../observation/types'

const causeLabels: Record<ProgressCause, string> = {
  manual: '수동 진행 완료', caregiver: '보호자 확인으로 진행',
  demo_observation: 'DEMO_OBSERVATION · 합성 관찰 조건 충족',
}

const titles: Record<PackingStep, string> = {
  find_bag: '가방 찾기',
  find_bottle: '물병 찾기',
  put_bottle_in_bag: '물병을 가방에 넣기',
  check_items: '준비물 확인하기',
  complete: '완료',
}

const currentStates = {
  active: { symbol: '▶', label: '현재 단계 · 진행 중' },
  paused: { symbol: '‖', label: '현재 단계 · 일시정지' },
  help_requested: { symbol: '!', label: '현재 단계 · 보호자 확인 대기' },
  stopped: { symbol: '■', label: '이 단계에서 중단' },
  completed: { symbol: '✓', label: '데모 완료' },
}

export default function TaskProgress({ state, history }: {
  state: PackingState; history: Partial<Record<PackingStep, ProgressCause>>
}) {
  const currentIndex = stepOrder.indexOf(state.currentStep)
  return (
    <section className="task-progress" aria-label="가방 챙기기 전체 진행 단계">
      <h3>전체 진행 단계</h3>
      <p role="status">현재 위치: {currentIndex + 1} / {stepOrder.length} · {titles[state.currentStep]}<br />
        {currentStates[state.taskStatus].label}</p>
      <ol className="task-progress-list">
        {stepOrder.map((step, index) => {
          const isCurrent = index === currentIndex
          const isPrevious = index < currentIndex
          const marker = isCurrent ? currentStates[state.taskStatus]
            : isPrevious ? { symbol: '✓', label: history[step] ? causeLabels[history[step]!] : '진행 기록 없음' }
              : { symbol: '○', label: '아직 시작하지 않음' }
          return (
            <li key={step} aria-current={isCurrent ? 'step' : undefined}
              className={`task-progress-item ${isCurrent ? `is-current is-${state.taskStatus}` : isPrevious ? 'is-previous' : 'is-upcoming'}`}>
              <span className="task-progress-symbol" aria-hidden="true">{marker.symbol}</span>
              <div><strong>{index + 1}. {titles[step]}</strong><span className="task-progress-label">{marker.label}</span></div>
            </li>
          )
        })}
      </ol>
      <p className="task-progress-note">단계 표시는 수동 입력 또는 합성 관찰 조건에 따른 데모 기록입니다. 실제 행동 완료 판정이 아닙니다.</p>
    </section>
  )
}
