import type { TFunction } from '../i18n'

/** The six welcome steps, in order; each is the value of `?step=`. */
export const WELCOME_STEPS = ['language', 'welcome', 'arena', 'cards', 'mtgo', 'done'] as const

export type WelcomeStep = (typeof WELCOME_STEPS)[number]

/** The step an address names; step 1 (the language) for a missing or unknown value. */
export function stepOf(param: string | null): WelcomeStep {
  return WELCOME_STEPS.find((step) => step === param) ?? 'language'
}

/** The step's place in the run, 1 to 6. */
export function stepNumber(step: WelcomeStep): number {
  return WELCOME_STEPS.indexOf(step) + 1
}

/** The step before or after, `null` at either end. */
export function neighbour(step: WelcomeStep, by: -1 | 1): WelcomeStep | null {
  return WELCOME_STEPS[WELCOME_STEPS.indexOf(step) + by] ?? null
}

/** The address of a step. */
export function stepHref(step: WelcomeStep): string {
  return `/welcome?step=${step}`
}

/** How long ago a download ran, from its age in hours: under an hour,
 *  under 48 hours in hours, else in days. */
export function agePhrase(hours: number, t: TFunction): string {
  if (hours < 1) return t('welcome.age.lessThanHour')
  if (hours < 48) return t('welcome.age.hours', { count: Math.floor(hours) })
  return t('welcome.age.days', { count: Math.floor(hours / 24) })
}

/** A sentence for a failure the shell wrote: with a full stop at its end. */
export function withStop(sentence: string): string {
  const trimmed = sentence.trim()
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`
}
