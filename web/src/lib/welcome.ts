import type { AppSettings } from '../bridge'

/** Every welcome step, in order; each is the value of `?step=`. A run shows
 *  only the ones `stepsFor` keeps. */
export const WELCOME_STEPS = ['start', 'plays', 'arena', 'mtgo', 'done'] as const

export type WelcomeStep = (typeof WELCOME_STEPS)[number]

/** Which clients the user plays, as the shell keeps it. */
export type Plays = AppSettings['plays']

/** The step an address names; Start for a missing, unknown or retired value
 *  (`?step=cards` from before the steps changed). */
export function stepOf(param: string | null): WelcomeStep {
  return WELCOME_STEPS.find((step) => step === param) ?? 'start'
}

/** The steps a run shows: Arena's and Magic Online's only when chosen. A
 *  missing or empty choice reads as both, as it does everywhere else. A
 *  `current` step the choice leaves out (an address typed by hand, or the
 *  choice not yet back from the shell) is kept in its place, so the step on
 *  show always has a number and neighbours. */
export function stepsFor(plays: Plays, current?: WelcomeStep): WelcomeStep[] {
  const chosen: readonly WelcomeStep[] = plays && plays.length > 0 ? plays : ['arena', 'mtgo']
  return WELCOME_STEPS.filter(
    (step) => step === current || (step !== 'arena' && step !== 'mtgo') || chosen.includes(step),
  )
}

/** The step's place in the steps shown, from 1. */
export function stepNumber(step: WelcomeStep, steps: readonly WelcomeStep[]): number {
  return steps.indexOf(step) + 1
}

/** The step shown before or after, `null` at either end. */
export function neighbour(step: WelcomeStep, by: -1 | 1, steps: readonly WelcomeStep[]): WelcomeStep | null {
  const at = steps.indexOf(step)
  if (at === -1) return null
  return steps[at + by] ?? null
}

/** The address of a step. */
export function stepHref(step: WelcomeStep): string {
  return `/welcome?step=${step}`
}

/** A sentence for a failure the shell wrote: with a full stop at its end. */
export function withStop(sentence: string): string {
  const trimmed = sentence.trim()
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`
}
