export type PackingStep = 'find_bag' | 'find_bottle' | 'put_bottle_in_bag' | 'check_items' | 'complete'
export type HelpLevel = 0 | 1 | 2 | 3 | 4
export type TaskStatus = 'active' | 'paused' | 'help_requested' | 'stopped' | 'completed'
export type HelpReason = 'capability_difficult' | 'capability_unknown' | 'user_requested' | 'help_limit' | null
export type PackingEvent = 'next' | 'more_help' | 'pause' | 'continue' | 'stop' | 'ask_for_help' | 'caregiver_confirm' | 'restart'
export type PackingState = {
  currentStep: PackingStep
  helpLevel: HelpLevel
  taskStatus: TaskStatus
  helpReason: HelpReason
}
export type PackingTarget = 'bag' | 'bottle' | 'opening' | 'inside'
export type VisualCue = 'none' | 'highlight' | 'arrow'
