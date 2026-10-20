import type { PackingStep, PackingTarget } from './types'

export const stepOrder: PackingStep[] = [
  'find_bag', 'find_bottle', 'put_bottle_in_bag', 'check_items', 'complete',
]

type StepDefinition = {
  title: string
  target: PackingTarget | null
  prompts: [string, string, string, string, string]
}

export const steps: Record<PackingStep, StepDefinition> = {
  find_bag: {
    title: '가방 찾기', target: 'bag',
    prompts: ['가방을 찾아보세요.', '주변을 천천히 살펴보세요.', '가방을 찾아보세요.',
      '가방을 보세요.', '보호자와 함께 가방을 찾아보세요.'],
  },
  find_bottle: {
    title: '물병 찾기', target: 'bottle',
    prompts: ['물병을 찾아보세요.', '주변을 천천히 살펴보세요.', '물병을 찾아보세요.',
      '물병을 보세요.', '보호자와 함께 물병을 찾아보세요.'],
  },
  put_bottle_in_bag: {
    title: '물병 넣기', target: 'opening',
    prompts: ['물병을 가방에 넣어보세요.', '가방 입구를 찾아보세요.', '가방 입구를 확인해 보세요.',
      '물병을 가방 입구로 옮겨보세요.', '보호자와 함께 물병을 넣어보세요.'],
  },
  check_items: {
    title: '준비물 확인', target: 'inside',
    prompts: ['가방 안에 물병이 있는지 확인해 보세요.', '가방 안을 살펴보세요.',
      '가방 안을 확인해 보세요.', '가방 안에 물병이 있는지 확인해 보세요.',
      '보호자에게 준비물 확인을 부탁해 보세요.'],
  },
  complete: {
    title: '완료', target: null,
    prompts: ['가방 챙기기 데모를 마쳤어요.', '가방 챙기기 데모를 마쳤어요.',
      '가방 챙기기 데모를 마쳤어요.', '가방 챙기기 데모를 마쳤어요.', '가방 챙기기 데모를 마쳤어요.'],
  },
}

// DEMO_SCENE fixtures in SVG viewBox coordinates, not camera observations.
export const targets: Record<PackingTarget, { x: number; y: number; width: number; height: number }> = {
  bag: { x: 205, y: 65, width: 140, height: 165 },
  bottle: { x: 65, y: 105, width: 45, height: 100 },
  opening: { x: 215, y: 80, width: 120, height: 35 },
  inside: { x: 225, y: 125, width: 100, height: 75 },
}
