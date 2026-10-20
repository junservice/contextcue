import { targets } from '../packing/steps'
import type { PackingTarget, VisualCue } from '../packing/types'

export default function PackingScene({ targetId, visualCue }: {
  targetId: PackingTarget | null
  visualCue: VisualCue
}) {
  const target = targetId ? targets[targetId] : null
  const centerX = target ? target.x + target.width / 2 : 0
  const centerY = target ? target.y + target.height / 2 : 0
  // Arrow points to a fixed fixture region; it does not represent detected movement.
  const startX = targetId === 'opening' ? 115 : centerX - 45
  const startY = targetId === 'opening' ? 120 : Math.max(20, centerY - 65)
  const angle = Math.atan2(centerY - startY, centerX - startX)
  const arrowPoint = (offset: number) =>
    `${centerX - 15 * Math.cos(angle + offset)},${centerY - 15 * Math.sin(angle + offset)}`
  return (
    <section aria-label="가방 챙기기 합성 장면">
      <h3>합성 장면 · DEMO_SCENE</h3>
      <svg viewBox="0 0 400 280" width="100%" role="img"
        aria-label="왼쪽에 물병, 오른쪽에 가방이 있는 고정 합성 장면. 실제 내용물과 행동 완료는 확인되지 않았습니다.">
        <rect x="1" y="1" width="398" height="278" fill="#ffffff" stroke="#334155" />
        <rect x="205" y="65" width="140" height="165" rx="16" fill="#dbeafe" stroke="#1e3a8a" strokeWidth="3" />
        <path d="M245 65 V45 H305 V65" fill="none" stroke="#1e3a8a" strokeWidth="4" />
        <rect x="215" y="80" width="120" height="35" rx="10" fill="#334155" />
        <text x="275" y="103" textAnchor="middle" fill="white" fontSize="16">가방 입구</text>
        <text x="275" y="163" textAnchor="middle" fill="#172554" fontSize="18">가방</text>
        <text x="275" y="190" textAnchor="middle" fill="#172554" fontSize="12">내용물 미확인</text>
        <rect x="65" y="105" width="45" height="100" rx="10" fill="#cffafe" stroke="#155e75" strokeWidth="3" />
        <rect x="76" y="90" width="23" height="15" fill="#155e75" />
        <text x="87" y="235" textAnchor="middle" fill="#172554" fontSize="18">물병</text>
        {target && visualCue === 'highlight' && (
          <rect x={target.x - 5} y={target.y - 5} width={target.width + 10} height={target.height + 10}
            fill="none" stroke="#9f1239" strokeWidth="5" strokeDasharray="8 4" />
        )}
        {target && visualCue === 'arrow' && (
          <g stroke="#9f1239" strokeWidth="5" fill="none">
            <line x1={startX} y1={startY} x2={centerX} y2={centerY} />
            <polyline points={`${arrowPoint(0.5)} ${centerX},${centerY} ${arrowPoint(-0.5)}`} />
          </g>
        )}
      </svg>
      <p>고정된 합성 그림입니다. 물병을 넣었다고 자동 표시하지 않습니다.</p>
    </section>
  )
}
