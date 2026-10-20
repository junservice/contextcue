import type { Profile } from '../types'
import { stepOrder } from './steps'
import type { HelpLevel, PackingEvent, PackingState, PackingStep } from './types'

export function initialPackingState(): PackingState {
  return { currentStep: 'find_bag', helpLevel: 0, taskStatus: 'active', helpReason: null }
}

function enterStep(currentStep: PackingStep, profile: Profile): PackingState {
  const state: PackingState = { currentStep, helpLevel: 0, taskStatus: 'active', helpReason: null }
  if (currentStep === 'complete') return { ...state, taskStatus: 'completed' }
  if (currentStep === 'put_bottle_in_bag') {
    const abilities = [profile.can_extend_arm, profile.can_grasp]
    if (abilities.includes(false)) {
      return { ...state, helpLevel: 4, taskStatus: 'help_requested', helpReason: 'capability_difficult' }
    }
    if (abilities.includes(null)) {
      return { ...state, helpLevel: 4, taskStatus: 'help_requested', helpReason: 'capability_unknown' }
    }
  }
  return state
}

export function canDispatch(state: PackingState, event: PackingEvent): boolean {
  if (event === 'restart') return true
  if (state.taskStatus === 'stopped' || state.taskStatus === 'completed') return false
  switch (event) {
    case 'next': return state.taskStatus === 'active'
    case 'more_help': return state.taskStatus === 'active' && state.helpLevel < 4
    case 'pause': return state.taskStatus === 'active'
    case 'continue': return state.taskStatus === 'paused'
    case 'stop': return true
    case 'ask_for_help': return state.taskStatus === 'active' || state.taskStatus === 'paused'
    case 'caregiver_confirm': return state.taskStatus === 'help_requested'
  }
}

export function transitionPacking(state: PackingState, event: PackingEvent, profile: Profile): PackingState {
  if (!canDispatch(state, event)) return state
  switch (event) {
    case 'restart': return initialPackingState()
    case 'next':
    case 'caregiver_confirm': {
      const nextStep = stepOrder[stepOrder.indexOf(state.currentStep) + 1]
      return nextStep ? enterStep(nextStep, profile) : state
    }
    case 'more_help': {
      const helpLevel = (state.helpLevel + 1) as HelpLevel
      return helpLevel === 4
        ? { ...state, helpLevel, taskStatus: 'help_requested', helpReason: 'help_limit' }
        : { ...state, helpLevel }
    }
    case 'pause': return { ...state, taskStatus: 'paused' }
    case 'continue': return { ...state, taskStatus: 'active' }
    case 'stop': return { ...state, taskStatus: 'stopped' }
    case 'ask_for_help':
      return { ...state, helpLevel: 4, taskStatus: 'help_requested', helpReason: 'user_requested' }
  }
}
