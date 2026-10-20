import { useRef, useState } from 'react'
import type { PlanRequest, PlanResponse, Profile, SceneObject } from './types'
import CaregiverSettings from './components/CaregiverSettings'
import PackingBagDemo from './components/PackingBagDemo'
import { initialPackingState, transitionPacking } from './packing/transitions'
import type { PackingEvent } from './packing/types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const milk: SceneObject = { id: 'milk_1', label: 'milk_carton', bbox: [0.40, 0.25, 0.60, 0.72] }
const cup: SceneObject = { id: 'cup_1', label: 'cup', bbox: [0.72, 0.48, 0.83, 0.69] }
const button: SceneObject = { id: 'button_1', label: 'door_button', bbox: [0.73, 0.28, 0.81, 0.39] }

function boxStyle(b: [number, number, number, number]) {
  return { left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%` }
}

export default function App() {
  const [view, setView] = useState<'api' | 'packing'>('packing')
  const [packingState, setPackingState] = useState(initialPackingState)
  const [packingNotice, setPackingNotice] = useState('')
  const [scenario, setScenario] = useState<'milk' | 'door'>('milk')
  const [instruction, setInstruction] = useState('A야, 우유 가져와야지')
  const [selectedUserId, setSelectedUserId] = useState<'demo_A' | 'demo_B'>('demo_A')
  const [profiles, setProfiles] = useState<Record<'demo_A' | 'demo_B', Profile>>({
    demo_A: {
      user_id: 'demo_A', can_extend_arm: true, can_grasp: true,
      can_press_button: null, preferred_guidance: ['visual_highlight'],
    },
    demo_B: {
      user_id: 'demo_B', can_extend_arm: false, can_grasp: null,
      can_press_button: false, preferred_guidance: ['arrow', 'voice'],
    },
  })
  const [result, setResult] = useState<PlanResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const requestVersion = useRef(0)
  const profile = profiles[selectedUserId]

  function resetPacking(notice: string) {
    setPackingState(initialPackingState())
    setPackingNotice(notice)
  }

  function handlePackingAction(event: PackingEvent) {
    setPackingState((previous) => transitionPacking(previous, event, profile))
    setPackingNotice('')
  }

  function clearResult() {
    requestVersion.current += 1
    setResult(null)
    setError(null)
    setLoading(false)
  }

  function changeUser(userId: 'demo_A' | 'demo_B') {
    if (userId === selectedUserId) return
    setSelectedUserId(userId)
    resetPacking('사용자가 변경되어 처음부터 시작합니다.')
    clearResult()
  }

  function changeCapability(
    capability: 'can_extend_arm' | 'can_grasp' | 'can_press_button', value: boolean | null,
  ) {
    if (profile[capability] === value) return
    resetPacking('설정이 변경되어 처음부터 시작합니다.')
    setProfiles((previous) => ({
      ...previous, [selectedUserId]: { ...previous[selectedUserId], [capability]: value },
    }))
    clearResult()
  }

  function toggleGuidance(guidance: Profile['preferred_guidance'][number]) {
    resetPacking('설정이 변경되어 처음부터 시작합니다.')
    setProfiles((previous) => {
      const current = previous[selectedUserId]
      return {
        ...previous,
        [selectedUserId]: {
          ...current,
          preferred_guidance: current.preferred_guidance.includes(guidance)
            ? current.preferred_guidance.filter((item) => item !== guidance)
            : [...current.preferred_guidance, guidance],
        },
      }
    })
    clearResult()
  }

  const scene_objects = scenario === 'milk' ? [milk, cup] : [button]
  const data: PlanRequest = {
    transcript: instruction,
    user_profile: profile,
    scene_objects,
  }

  async function send() {
    const version = ++requestVersion.current
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const resp = await fetch(`${API_BASE}/api/plan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
      })
      const body: PlanResponse | { detail?: string } = await resp.json()
      if (version !== requestVersion.current) return
      if (!resp.ok) throw new Error(('detail' in body && body.detail) || `HTTP ${resp.status}`)
      setResult(body as PlanResponse)
    } catch (e) {
      if (version === requestVersion.current) {
        setError(e instanceof Error ? e.message : 'Unknown error')
      }
    } finally {
      if (version === requestVersion.current) setLoading(false)
    }
  }

  function selectScenario(value: 'milk' | 'door') {
    if (value === scenario) return
    setScenario(value)
    setInstruction(value === 'milk' ? 'A야, 우유 가져와야지' : 'A야, 문 버튼 눌러보자')
    clearResult()
  }

  return (
    <main className="page">
      <header>
        <span className="eyebrow">ContextCue / MVP prototype</span>
        <h1>상황을 이해하는 한 가지 단서</h1>
        <p>가상 사용자 프로필과 모의 장면을 이용한 개발 테스트 화면입니다. 현재 장면은 실제 카메라 인식 결과가 아닙니다.</p>
      </header>
      <div className="tabs" role="group" aria-label="데모 화면 선택">
        <button type="button" aria-pressed={view === 'packing'} onClick={() => setView('packing')}>가방 챙기기</button>
        <button type="button" aria-pressed={view === 'api'} onClick={() => setView('api')}>기존 우유·자동문 API 데모</button>
      </div>
      <div className="layout">
        <section className="panel controls" aria-label="데모 설정">
          <CaregiverSettings selectedUserId={selectedUserId} profile={profile}
            onUserChange={changeUser} onCapabilityChange={changeCapability}
            onGuidanceToggle={toggleGuidance} />
          {view === 'api' && <>
          <h2>테스트 설정</h2>
          <label>시나리오</label>
          <div className="tabs" role="group" aria-label="시나리오 선택">
            <button aria-pressed={scenario === 'milk'} onClick={() => selectScenario('milk')}>우유 가져오기</button>
            <button aria-pressed={scenario === 'door'} onClick={() => selectScenario('door')}>자동문 버튼</button>
          </div>
          <label htmlFor="instruction">발화 텍스트 (ASR 미연결)</label>
          <textarea id="instruction" rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)} />
          <button className="primary" onClick={send} disabled={loading || !instruction.trim()}>
            {loading ? '판단 중…' : '단서 생성'}</button>
          <p className="note">실제 Nebius 호출 여부는 백엔드의 <code>PLANNER_MODE</code>로 결정됩니다. API 키는 서버에만 보관합니다.</p>
          </>}
        </section>
        {view === 'packing' ? (
          <PackingBagDemo profile={profile} state={packingState} notice={packingNotice} onAction={handlePackingAction} />
        ) : <section className="panel stage" aria-label="단서 표시">
          <div className="stage-heading"><h2>사용자 화면</h2><span className="pill">DEMO_SCENE · 합성 장면</span></div>
          <div className={`scene ${scenario}`} role="img" aria-label="임의로 그린 모의 장면. 실제 사물 검출 영상이 아닙니다.">
            {scenario === 'milk' ? (
              <>
                <span className="table-surface" />
                <span className="milk-shape"><b>MILK</b><small>우유</small></span>
                <span className="cup-shape" />
              </>
            ) : (
              <><span className="door-shape" /><span className="button-shape">●</span></>
            )}
            {result?.status === 'cue' && result.bbox && (
              <span className="highlight" style={boxStyle(result.bbox)} aria-label="검증된 목표 물체 강조" />
            )}
          </div>
          {error && <p className="feedback error" role="alert">서버 오류: {error}</p>}
          {result && <div className="feedback" role="status">
            <strong>{result.cue_text}</strong>
            <div className="meta"><span>{result.status}</span><span>{result.mode}</span><span>{result.reason}</span></div>
          </div>}
          {!error && !result && <p className="feedback muted">설정을 선택하고 단서 생성을 눌러주세요.</p>}
        </section>}
      </div>
      <footer>개발 단계: 모의 장면 / 텍스트 지시 / 보조자 확인 기반 시나리오만 구현됨</footer>
    </main>
  )
}
