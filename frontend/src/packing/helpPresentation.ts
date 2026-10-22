import type { Profile } from '../types'
import { steps } from './steps'
import type { PackingState, VisualCue } from './types'

const levels = [
  { name: '스스로 시도', meaning: '추가 위치 표시 없이 현재 안내를 보고 천천히 시도합니다.' },
  { name: '간단한 힌트', meaning: '짧은 힌트로 살펴볼 곳이나 행동을 안내합니다.' },
  { name: '대상 위치 강조', meaning: '선택한 안내 방식에 따라 대상 위치를 강조합니다.' },
  { name: '구체적인 위치 안내', meaning: '선택한 안내 방식에 따라 대상 위치를 더 구체적으로 안내합니다.' },
  { name: '보호자 확인 또는 도움', meaning: '직접 진행을 멈추고 보호자 확인이나 도움을 기다립니다.' },
] as const

const targetNames = { bag: '가방', bottle: '물병', opening: '가방 입구', inside: '가방 안쪽' }

// Presentation only: never dispatch an event or change the profile/task state.
export function helpPresentation(state: PackingState, profile: Profile) {
  const level = levels[state.helpLevel]
  const guidance = profile.preferred_guidance
  const target = steps[state.currentStep].target
  const targetName = target ? targetNames[target] : ''
  let visualCue: VisualCue = 'none'
  if (state.taskStatus === 'active') {
    if (state.helpLevel === 2 && guidance.includes('visual_highlight')) visualCue = 'highlight'
    if (state.helpLevel === 3) {
      if (guidance.includes('arrow')) visualCue = 'arrow'
      else if (guidance.includes('visual_highlight')) visualCue = 'highlight'
    }
  }

  const reasons: string[] = []
  if (state.taskStatus === 'paused') {
    reasons.push('잠시 멈춤을 선택하여 위치 안내를 잠시 숨겼습니다.')
  } else if (state.taskStatus === 'stopped') {
    reasons.push('작업을 중단하여 위치 안내를 제공하지 않습니다.')
  } else if (state.taskStatus === 'completed') {
    reasons.push('데모를 마쳐 추가 위치 안내를 제공하지 않습니다. 실제 준비 완료 여부는 확인되지 않았습니다.')
  } else if (state.taskStatus === 'help_requested') {
    if (state.helpReason === 'user_requested') {
      reasons.push('보호자 도움 요청을 선택하여 확인을 기다리고 있습니다.')
    } else if (state.helpReason === 'help_limit') {
      reasons.push('도움 더 보기를 통해 마지막 도움 단계에 도달하여 보호자 확인을 안내합니다.')
    } else if (state.currentStep === 'put_bottle_in_bag' &&
      (state.helpReason === 'capability_difficult' || state.helpReason === 'capability_unknown')) {
      const abilities = [
        { label: '팔 뻗기', value: profile.can_extend_arm },
        { label: '물건 잡기', value: profile.can_grasp },
      ]
      for (const ability of abilities.filter((item) => item.value === false)) {
        reasons.push(`${ability.label} 동작이 어려움으로 설정되어 보호자 도움이 필요합니다.`)
      }
      for (const ability of abilities.filter((item) => item.value === null)) {
        reasons.push(`${ability.label} 능력이 미확인 상태이므로 먼저 보호자 확인이 필요합니다.`)
      }
    } else {
      reasons.push('현재 단계에서 보호자 확인이나 도움을 기다리고 있습니다.')
    }
  } else if (visualCue === 'highlight') {
    reasons.push(`대상 강조 안내를 선택하여 ${targetName} 위치를 표시합니다.`)
  } else if (visualCue === 'arrow') {
    reasons.push(`화살표 안내를 선택하여 ${targetName} 위치를 화살표로 표시합니다.`)
  } else if (state.helpLevel === 0) {
    reasons.push('스스로 시도할 수 있도록 추가 위치 표시 없이 현재 할 일을 글로 안내합니다. 시간 제한은 없습니다.')
  } else if (state.helpLevel === 1) {
    reasons.push('도움 더 보기를 선택하여 현재 단계의 간단한 힌트를 글로 안내합니다.')
  } else if (state.helpLevel === 2) {
    reasons.push('대상 강조 안내를 선택하지 않아 강조 표시는 제공하지 않습니다. 현재 안내를 글로 확인해 주세요.')
  } else {
    reasons.push('화살표와 대상 강조 안내를 선택하지 않아 현재 안내를 글로 제공합니다.')
  }
  if (state.taskStatus === 'active' && !guidance.length) {
    reasons.push('선호 안내 방식이 설정되지 않아 짧은 글로 안내합니다.')
  }
  return {
    ...level,
    visualCue,
    methods: visualCue === 'highlight' ? '짧은 글 안내 · 대상 강조 표시'
      : visualCue === 'arrow' ? '짧은 글 안내 · 화살표 안내' : '짧은 글 안내',
    reasons,
    voicePending: guidance.includes('voice'),
  }
}
