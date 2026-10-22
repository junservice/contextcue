import type { Profile } from '../types'
import type { PackingEvent, PackingState, PackingStep } from '../packing/types'

export type ObservationToken = { sessionId: number; stepEntryId: number; evidenceEpoch: number }
export type DemoObservation = ObservationToken & {
  source: 'DEMO_OBSERVATION'
  type: 'bag_detected' | 'user_oriented_to_bag' | 'bottle_detected' | 'user_oriented_to_bottle'
    | 'user_reached_for_bottle' | 'bottle_near_bag_opening' | 'bottle_inside_bag'
    | 'items_confirmed' | 'observation_uncertain' | 'object_lost'
  eventId: string
  observationId: string
  objectId: 'bag' | 'bottle'
  observedAtMs: number
}
export type ProgressCause = 'manual' | 'caregiver' | 'demo_observation'
export type DemoProgressState = ObservationToken & {
  packing: PackingState
  history: Partial<Record<PackingStep, ProgressCause>>
  bagLocated: boolean
  bottleLocated: boolean
  reachedForBottle: boolean
  nearBagOpening: boolean
  orientationTimes: number[]
  seenEventIds: string[]
  seenObservationIds: string[]
  lastObservedAt: number | null
  message: string
  pendingAuto: boolean
  seenManualIds: string[]
}
export type DemoProgressAction =
  | { kind: 'reset'; notice: string }
  | { kind: 'manual'; event: PackingEvent; profile: Profile; token: ObservationToken; inputId: string }
  | { kind: 'observation'; observation: DemoObservation; profile: Profile }
  | { kind: 'commit_auto'; token: ObservationToken; profile: Profile }
