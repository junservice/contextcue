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

// Phase 5 /api/v1/tasks mirrors backend/app/task_api.py and its domain models.
// Candidate bindings/Evidence are untrusted. No UI or source adapter is connected yet.
export type TaskTargetRef = {
  target_key: string
  concept: string
  qualifiers: Partial<Record<'color' | 'relative_position', string>>
}

export type TaskBinding = {
  target_key: string
  object_id: string
  observation_revision: string
}

export type TaskStep = {
  step_id: string
  action: string
  target_keys: string[]
  completion_goal: { outcome: string; target_keys: string[] }
  max_help_level: number
}

export type TaskPlan = {
  schema_version: '1.0'
  plan_id: string
  goal: string
  targets: TaskTargetRef[]
  steps: TaskStep[]
}

export type TaskEvidence = {
  evidence_id: string
  step_id: string
  source: 'camera_observation' | 'caregiver_report' | 'manual_progress' |
    'cue_issued' | 'model_assessment' | 'unknown'
  outcome: string
  target_keys: string[]
  object_ids: string[]
  observation_revision: string | null
  provenance_id: string | null
  confidence: number | null
  relation: 'supports' | 'contradicts' | 'inconclusive'
}

export type TaskControlType = 'pause' | 'resume' | 'stop' | 'refusal' |
  'more_help' | 'help_requested' | 'manual_advance'

export type TaskEvent =
  | { type: TaskControlType; step_id?: string | null; binding?: null; evidence?: null }
  | { type: 'cue_issued'; step_id: string; binding?: null; evidence?: null }
  | { type: 'target_bound'; step_id?: string | null; binding: TaskBinding; evidence?: null }
  | { type: 'evidence_received'; step_id?: string | null; binding?: null; evidence: TaskEvidence }

export type TaskState = {
  task_id: string
  plan_id: string
  status: 'idle' | 'active' | 'paused' | 'needs_confirmation' |
    'needs_assistance' | 'stopped' | 'completed'
  current_step_id: string | null
  steps: {
    step_id: string
    status: 'pending' | 'active' | 'awaiting_target' | 'awaiting_evidence' | 'completed' | 'blocked'
    help_level: number
  }[]
  target_bindings: Record<string, TaskBinding>
  evidence: TaskEvidence[]
}

export type TaskCue = {
  step_id: string
  help_level: number
  kind: 'text' | 'voice' | 'visual_highlight' | 'arrow' | 'assistance'
  text: string
  object_id: string | null
  observation_revision: string | null
}

export type TaskServiceEvent = {
  kind: 'task_started' | 'control_accepted' | 'binding_accepted' | 'evidence_accepted' |
    'cue_issued' | 'step_completed' | 'task_completed' | 'verification_blocked'
  step_id: string | null
  reason_code: string
  evidence_ids: string[]
  cue: TaskCue | null
}

export type TaskCreateRequest = {
  goal: string
  transcript: string
  user_profile: Profile
}

export type TaskEventRequest = {
  event_id: string
  expected_version: number
  event: TaskEvent
}

export type TaskSessionResponse = {
  task_id: string
  version: number
  plan: TaskPlan
  state: TaskState
  mode: 'MOCK_PROVIDER' | 'LIVE_NEBIUS' | 'TEMPLATE'
  accepted: boolean
  reason_code: string
  cue: TaskCue | null
  events: TaskServiceEvent[]
}

export type TaskCreateResponse = {
  decision: 'allow' | 'confirm' | 'assist' | 'stop'
  reason_code: string
  session: TaskSessionResponse | null
}
