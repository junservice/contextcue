import { useState } from 'react'
import type { PlanRequest, PlanResponse, SceneObject } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const milk: SceneObject = { id: 'milk_1', label: 'milk_carton', bbox: [0.40, 0.25, 0.60, 0.72] }
const cup: SceneObject = { id: 'cup_1', label: 'cup', bbox: [0.72, 0.48, 0.83, 0.69] }
const button: SceneObject = { id: 'button_1', label: 'door_button', bbox: [0.73, 0.28, 0.81, 0.39] }

function boxStyle(b: [number, number, number, number]) {
  return { left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%` }
}

export default function App() {
  const [scenario, setScenario] = useState<'milk' | 'door'>('milk')
  const [instruction, setInstruction] = useState('A야, 우유 가져와야지')
  const [ability, setAbility] = useState<'yes' | 'no' | 'unknown'>('yes')
  const [result, setResult] = useState<PlanResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const scene_objects = scenario === 'milk' ? [milk, cup] : [button]
  const data: PlanRequest = {
    transcript: instruction,
    user_profile: {
      user_id: 'demo_A',
      can_grasp: scenario === 'milk' ? (ability === 'unknown' ? null : ability === 'yes') : null,
      can_press_button: scenario === 'door' ? (ability === 'unknown' ? null : ability === 'yes') : null,
      can_extend_arm: null,
      preferred_guidance: [],
    },
    scene_objects,
  }

  async function send() {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const resp = await fetch(`${API_BASE}/api/plan`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
      })
      const body: PlanResponse | { detail?: string } = await resp.json()
      if (!resp.ok) throw new Error(('detail' in body && body.detail) || `HTTP ${resp.status}`)
      setResult(body as PlanResponse)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
    } finally {
      setLoading(false)
    }
  }

  function selectScenario(value: 'milk' | 'door') {
    setScenario(value)
    setInstruction(value === 'milk' ? 'A야, 우유 가져와야지' : 'A야, 문 버튼 눌러보자')
    setResult(null)
    setError(null)
  }

  return (
    <main className="page">
      <header>
        <span className="eyebrow">ContextCue / MVP prototype</span>
        <h1>상황을 이해하는 한 가지 단서</h1>
        <p>가상 사용자 프로필과 모의 장면을 이용한 개발 테스트 화면입니다. 현재 장면은 실제 카메라 인식 결과가 아닙니다.</p>
      </header>
      <div className="layout">
        <section className="panel controls" aria-label="데모 설정">
          <h2>테스트 설정</h2>
          <label>시나리오</label>
          <div className="tabs" role="group" aria-label="시나리오 선택">
            <button aria-pressed={scenario === 'milk'} onClick={() => selectScenario('milk')}>우유 가져오기</button>
            <button aria-pressed={scenario === 'door'} onClick={() => selectScenario('door')}>자동문 버튼</button>
          </div>
          <label htmlFor="instruction">발화 텍스트 (ASR 미연결)</label>
          <textarea id="instruction" rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)} />
          <label htmlFor="ability">사용자의 해당 동작 능력</label>
          <select id="ability" value={ability} onChange={(e) => setAbility(e.target.value as 'yes' | 'no' | 'unknown')}>
            <option value="yes">가능</option>
            <option value="no">불가능</option>
            <option value="unknown">확인되지 않음</option>
          </select>
          <button className="primary" onClick={send} disabled={loading || !instruction.trim()}>
            {loading ? '판단 중…' : '단서 생성'}</button>
          <p className="note">실제 Nebius 호출 여부는 백엔드의 <code>PLANNER_MODE</code>로 결정됩니다. API 키는 서버에만 보관합니다.</p>
        </section>
        <section className="panel stage" aria-label="단서 표시">
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
        </section>
      </div>
      <footer>개발 단계: 모의 장면 / 텍스트 지시 / 보조자 확인 기반 시나리오만 구현됨</footer>
    </main>
  )
}
