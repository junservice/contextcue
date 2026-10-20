import type { Profile } from '../types'

const guidanceLabels = {
  visual_highlight: '대상 강조 표시',
  arrow: '화살표 안내',
  voice: '음성 안내',
}

function abilityLabel(value: boolean | null) {
  return value === null ? '미확인' : value ? '가능' : '어려움'
}

export default function ProfileSummary({ profile }: { profile: Profile }) {
  return (
    <section aria-label="현재 설정 요약">
      <h3>현재 설정 요약</h3>
      <p>{profile.user_id === 'demo_A' ? '사용자 A' : '사용자 B'}</p>
      <dl>
        <dt>팔 뻗기</dt><dd>{abilityLabel(profile.can_extend_arm)}</dd>
        <dt>물건 잡기</dt><dd>{abilityLabel(profile.can_grasp)}</dd>
        <dt>버튼 정확히 누르기</dt><dd>{abilityLabel(profile.can_press_button)}</dd>
        <dt>선호 안내 방식</dt>
        <dd>{profile.preferred_guidance.length
          ? profile.preferred_guidance.map((item) => guidanceLabels[item]).join(', ')
          : '선택한 안내 방식 없음'}</dd>
      </dl>
    </section>
  )
}
