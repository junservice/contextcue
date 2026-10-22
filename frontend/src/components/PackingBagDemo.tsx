import type { Profile } from '../types'
import { stepOrder, steps } from '../packing/steps'
import type { PackingEvent, PackingState } from '../packing/types'
import { helpPresentation } from '../packing/helpPresentation'
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
  const presentation = helpPresentation(state, profile)
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
      <p>DEMO_RULES · 미리 정한 규칙으로 안내하는 데모입니다. 이 화면은 API나 AI를 호출하지 않습니다.</p>
      <p>합성 장면을 사용하는 데모입니다. 실제 행동을 자동으로 확인하지 않습니다.</p>
      <p>{profile.user_id === 'demo_A' ? '사용자 A' : '사용자 B'}의 작업</p>
      {notice && <p role="status">{notice}</p>}
      <h3>진행 상황</h3>
      <p>{stepOrder.indexOf(state.currentStep) + 1} / 5 · {step.title}</p>
      <p>{statusLabels[state.taskStatus]}</p>
      <PackingScene targetId={step.target} visualCue={presentation.visualCue} />
      <h3>현재 안내</h3>
      <p role="status">{prompt}</p>
      <section className="help-explanation" aria-label="현재 도움 설명" aria-live="polite">
        {state.taskStatus !== 'completed' && <>
          <h3>현재 도움: {presentation.name}</h3>
          <p>도움 수준 {state.helpLevel} / 4{state.taskStatus === 'paused' || state.taskStatus === 'stopped' ? ' · 위치 안내 중지 중' : ''}</p>
          {state.taskStatus !== 'paused' && state.taskStatus !== 'stopped' && <p>{presentation.meaning}</p>}
        </>}
        <p><strong>제공 중인 안내:</strong> {presentation.methods}</p>
        <h4>안내 이유</h4>
        {presentation.reasons.map((reason) => <p key={reason}>{reason}</p>)}
        {presentation.voicePending && <p>음성 재생 준비 중 · 현재는 소리가 재생되지 않습니다.</p>}
      </section>
      {!guidance.length && <p>선호하는 안내 방식이 아직 설정되지 않았어요. 짧은 텍스트로 안내합니다.</p>}
      {state.taskStatus === 'active' && state.helpLevel === 0 && <p>천천히 해보세요. 시간 제한은 없습니다.</p>}
      {state.currentStep === 'put_bottle_in_bag' && state.taskStatus === 'active' &&
        <p>데모 프로필만으로 모든 신체 조건이 확인되는 것은 아닙니다. 필요하면 도움을 요청해 주세요.</p>}
      {state.taskStatus === 'help_requested' && <p>실제 알림은 전송되지 않습니다. 보호자 확인은 현재 단계의 수동 진행 입력입니다.</p>}
      {state.taskStatus === 'completed' && <p>단계를 직접 넘겨 종료한 데모입니다. 실제 준비 완료 여부는 확인되지 않았습니다.</p>}
      <p>‘다음’은 현재 데모의 임시 수동 진행 버튼입니다. 실제 행동의 성공을 판정하지 않습니다.</p>
      <p className="packing-future-note">향후 구현 예정: 카메라 관찰 이벤트로 행동 완료가 확인되면 자동으로 다음 단계로 이동하는 구조를 목표로 합니다. 현재는 카메라가 연결되어 있지 않습니다.</p>
      <TaskControls state={state} onAction={onAction} />
      <ProfileSummary profile={profile} />
    </section>
  )
}
