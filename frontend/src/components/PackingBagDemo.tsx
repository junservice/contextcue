import type { Profile } from '../types'
import { stepOrder, steps } from '../packing/steps'
import type { PackingEvent, PackingState, VisualCue } from '../packing/types'
import PackingScene from './PackingScene'
import ProfileSummary from './ProfileSummary'
import TaskControls from './TaskControls'

const statusLabels = {
  active: '진행 중', paused: '잠시 멈췄어요.', help_requested: '보호자 확인이 필요해요.',
  stopped: '작업을 종료했어요.', completed: '가방 챙기기 데모를 마쳤어요.',
}

export default function PackingBagDemo({ profile, state, notice, onAction }: {
  profile: Profile
  state: PackingState
  notice: string
  onAction: (event: PackingEvent) => void
}) {
  const step = steps[state.currentStep]
  const guidance = profile.preferred_guidance
  let visualCue: VisualCue = 'none'
  if (state.taskStatus === 'active') {
    if (state.helpLevel === 2 && guidance.includes('visual_highlight')) visualCue = 'highlight'
    if (state.helpLevel === 3) {
      if (guidance.includes('arrow')) visualCue = 'arrow'
      else if (guidance.includes('visual_highlight')) visualCue = 'highlight'
    }
  }
  let prompt = step.prompts[state.helpLevel]
  if (state.taskStatus === 'paused' || state.taskStatus === 'stopped') {
    prompt = statusLabels[state.taskStatus]
  } else if (state.taskStatus === 'help_requested') {
    switch (state.helpReason) {
      case 'capability_difficult':
        prompt = '이 동작은 도움이 필요해요. 보호자와 함께 해볼까요?'
        break
      case 'capability_unknown':
        prompt = '물병을 잡고 가방에 넣을 수 있는지 아직 확인되지 않았어요. 보호자와 먼저 확인해 주세요.'
        break
      case 'user_requested': prompt = '보호자에게 도움을 요청해 주세요.'; break
      default: prompt = step.prompts[4]
    }
  }
  return (
    <section className="panel" aria-label="가방 챙기기 데모">
      <h2>가방 챙기기</h2>
      <p>DEMO_RULES · 이 화면은 API나 AI를 호출하지 않습니다.</p>
      <p>합성 장면을 사용하는 데모입니다. 실제 행동을 자동으로 확인하지 않습니다.</p>
      <p>{profile.user_id === 'demo_A' ? '사용자 A' : '사용자 B'}의 작업</p>
      {notice && <p role="status">{notice}</p>}
      <h3>진행 상황</h3>
      <p>{stepOrder.indexOf(state.currentStep) + 1} / 5 · {step.title}</p>
      {state.taskStatus !== 'completed' && <p>도움 수준 {state.helpLevel} / 4</p>}
      <p>{statusLabels[state.taskStatus]}</p>
      <PackingScene targetId={step.target} visualCue={visualCue} />
      <h3>현재 안내</h3>
      <p role="status">{prompt}</p>
      {!guidance.length && <p>선호하는 안내 방식이 아직 설정되지 않았어요. 짧은 텍스트로 안내합니다.</p>}
      {guidance.includes('voice') && <p>음성 안내 선호 · 재생 미구현</p>}
      {state.taskStatus === 'active' && state.helpLevel === 0 && <p>천천히 해보세요. 시간 제한은 없습니다.</p>}
      {state.currentStep === 'put_bottle_in_bag' && state.taskStatus === 'active' &&
        <p>데모 프로필만으로 모든 신체 조건이 확인되는 것은 아닙니다. 필요하면 도움을 요청해 주세요.</p>}
      {state.taskStatus === 'help_requested' && <p>실제 알림은 전송하지 않습니다. 보호자 확인은 현재 단계의 수동 진행 입력입니다.</p>}
      {state.taskStatus === 'completed' && <p>단계를 직접 넘겨 종료한 데모입니다. 실제 준비 완료 여부는 확인되지 않았습니다.</p>}
      <p>‘다음’은 사용자의 수동 진행 입력입니다. 실제 행동의 성공 판정이 아닙니다.</p>
      <TaskControls state={state} onAction={onAction} />
      <ProfileSummary profile={profile} />
    </section>
  )
}
