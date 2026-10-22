import { canDispatch } from '../packing/transitions'
import type { PackingEvent, PackingState } from '../packing/types'

const groups: { id: string; title: string; descriptions: string[]; actions: { event: PackingEvent; label: string }[] }[] = [
  {
    id: 'progress', title: '주요 진행',
    descriptions: [
      '‘다음’은 임시 수동 진행 버튼이며 실제 행동 성공을 자동 판정하지 않습니다.',
      '‘보호자 확인 후 계속’은 보호자가 확인한 뒤 현재 단계를 수동으로 넘기는 입력입니다.',
    ],
    actions: [
      { event: 'next', label: '다음' },
      { event: 'continue', label: '계속하기' },
      { event: 'caregiver_confirm', label: '보호자 확인 후 계속' },
    ],
  },
  {
    id: 'help', title: '도움',
    descriptions: ['‘보호자 도움 요청’은 데모 상태만 변경하며 실제 알림을 전송하지 않습니다.'],
    actions: [
      { event: 'more_help', label: '도움 더 보기' },
      { event: 'ask_for_help', label: '보호자 도움 요청' },
    ],
  },
  {
    id: 'stop', title: '중단·초기화',
    descriptions: ['‘잠시 멈춤’은 이어서 진행할 수 있고, ‘작업 종료’ 후에는 처음부터 다시 시작할 수 있습니다.'],
    actions: [
      { event: 'pause', label: '잠시 멈춤' },
      { event: 'stop', label: '작업 종료' },
      { event: 'restart', label: '처음부터 시작' },
    ],
  },
]

export default function TaskControls({ state, onAction }: {
  state: PackingState
  onAction: (event: PackingEvent) => void
}) {
  return (
    <section className="task-controls" aria-label="가방 챙기기 조작">
      <h3>조작</h3>
      {groups.map((group) => (
        <fieldset className={`task-control-group task-control-${group.id}`} key={group.id}>
          <legend>{group.title}</legend>
          <div className="task-control-buttons">
            {group.actions.map(({ event, label }) => (
              <button key={event} type="button" disabled={!canDispatch(state, event)}
                aria-describedby={`task-control-${group.id}-description`}
                onClick={() => onAction(event)}>{label}</button>
            ))}
          </div>
          <div id={`task-control-${group.id}-description`}>
            {group.descriptions.map((description) => <p key={description}>{description}</p>)}
          </div>
        </fieldset>
      ))}
    </section>
  )
}
