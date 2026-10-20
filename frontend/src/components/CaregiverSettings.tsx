import type { Profile } from '../types'
import ProfileSummary from './ProfileSummary'

type Capability = 'can_extend_arm' | 'can_grasp' | 'can_press_button'
type Guidance = Profile['preferred_guidance'][number]

type Props = {
  selectedUserId: 'demo_A' | 'demo_B'
  profile: Profile
  onUserChange: (userId: 'demo_A' | 'demo_B') => void
  onCapabilityChange: (capability: Capability, value: boolean | null) => void
  onGuidanceToggle: (guidance: Guidance) => void
}

const capabilities: { key: Capability; label: string }[] = [
  { key: 'can_extend_arm', label: '팔 뻗기' },
  { key: 'can_grasp', label: '물건 잡기' },
  { key: 'can_press_button', label: '버튼 정확히 누르기' },
]

const guidanceOptions: { key: Guidance; label: string }[] = [
  { key: 'visual_highlight', label: '대상 강조 표시' },
  { key: 'arrow', label: '화살표 안내' },
  { key: 'voice', label: '음성 안내' },
]

export default function CaregiverSettings({
  selectedUserId, profile, onUserChange, onCapabilityChange, onGuidanceToggle,
}: Props) {
  return (
    <section aria-label="보호자 설정">
      <h2>보호자 설정</h2>
      <p>사용자의 능력과 선호하는 안내 방식을 설정해 주세요.</p>
      <p>사용자 A와 B는 실제 개인정보가 없는 합성 데모 사용자입니다.</p>
      <p>설정은 이 페이지에서만 유지됩니다. 새로고침하면 초기값으로 돌아갑니다.</p>
      <label htmlFor="profile-user">사용자 선택</label>
      <select id="profile-user" value={selectedUserId}
        onChange={(event) => onUserChange(event.target.value as Props['selectedUserId'])}>
        <option value="demo_A">사용자 A</option>
        <option value="demo_B">사용자 B</option>
      </select>
      <h3>사용자 능력</h3>
      <p>각 동작을 할 수 있는지 선택해 주세요. 아직 모르면 ‘미확인’을 선택해 주세요.</p>
      {capabilities.map(({ key, label }) => (
        <div key={key}>
          <label htmlFor={key}>{label}</label>
          <select id={key} value={profile[key] === null ? 'unknown' : profile[key] ? 'yes' : 'no'}
            onChange={(event) => onCapabilityChange(key,
              event.target.value === 'unknown' ? null : event.target.value === 'yes')}>
            <option value="yes">가능</option>
            <option value="no">어려움</option>
            <option value="unknown">미확인</option>
          </select>
        </div>
      ))}
      <fieldset>
        <legend>선호하는 안내 방식</legend>
        <p>여러 개를 선택할 수 있습니다. 모두 해제할 수도 있습니다.</p>
        {guidanceOptions.map(({ key, label }) => (
          <label key={key}>
            <input type="checkbox" checked={profile.preferred_guidance.includes(key)}
              onChange={() => onGuidanceToggle(key)} />
            {label}
          </label>
        ))}
      </fieldset>
      <p>안내 선호만 설정합니다. 이 화면에서 안내를 실행하지는 않습니다.</p>
      {!profile.preferred_guidance.length &&
        <p>선호하는 안내 방식이 아직 설정되지 않았어요.</p>}
      <ProfileSummary profile={profile} />
    </section>
  )
}
