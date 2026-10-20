// Mirrors backend/app/schemas.py. Update these types together in one PR.
export type SceneObject = {
  id: string
  label: string
  bbox: [number, number, number, number]
}

export type Profile = {
  user_id: string
  can_grasp: boolean | null
  can_press_button: boolean | null
  can_extend_arm: boolean | null
  preferred_guidance: ('visual_highlight' | 'arrow' | 'voice')[]
}

export type PlanRequest = {
  transcript: string
  user_profile: Profile
  scene_objects: SceneObject[]
}

export type PlanResponse = {
  status: 'cue' | 'needs_confirmation' | 'needs_assistance' | 'unavailable'
  cue_text: string
  object_id: string | null
  bbox: [number, number, number, number] | null
  mode: 'DEMO_RULES' | 'LIVE_NEBIUS'
  scene_mode: 'DEMO_SCENE'
  reason: string
}
