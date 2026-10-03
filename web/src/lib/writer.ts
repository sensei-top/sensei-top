/**
 * Who writes a report, read from what the API says of a key and what the
 * shell says of the plan, and the sentences a report's card says of it.
 * A plan that writes comes first, then a key of the viewer's; with
 * neither, nobody writes it and the prompt is there to copy. The counts
 * are the shell's estimate, drawn as they come.
 */
import type { Plan, ReportKind } from '../bridge'
import { ALLOWANCE_USED, allowanceUsed, startsAgainSentence } from './plan'
import { formatCount } from './time'

/** Who writes a report. `offered`: a plan is sold to a viewer who has
 *  none. `about`: about how many of this kind the allowance still writes,
 *  `null` when the shell gave no count. `startsAgain`: the day the
 *  allowance starts again, `null` on a trial, whose never does. */
export type Writer =
  | { by: 'nobody'; offered: boolean }
  | { by: 'key' }
  | { by: 'plan'; about: number | null; used: boolean; startsAgain: string | null }

/** The sentence under the copy buttons when a plan is offered, before its
 *  link. */
export const OFFER_SENTENCE = 'Pro writes this for you.'

/** The words of the link after `OFFER_SENTENCE`. */
export const OFFER_LINK = 'See the plan'

/** Where `OFFER_LINK` goes. */
export const OFFER_HREF = '/settings#plan'

/** The part of a used allowance's sentence after its day, or all of it on
 *  a trial. */
const USED_THEN = 'The prompt is here to copy until then.'
const TRIAL_USED = "The trial's allowance is used. The prompt is here to copy."

/** Who writes a report of `kind`. `status` is the API's answer on the
 *  key, `undefined` or `null` before it answers; `plan` is the shell's,
 *  `null` with no shell. A plan in trial, running or whose payment failed
 *  writes; its allowance counts as used when no kind has any left or this
 *  kind has none. Else a key writes; else nobody, and a plan is offered
 *  when there is none or it ended. */
export function writerFrom(
  status: { configured: boolean } | null | undefined,
  plan: Plan | null,
  kind: ReportKind,
): Writer {
  if (plan && (plan.state === 'trial' || plan.state === 'active' || plan.state === 'payment-failed')) {
    const { allowance } = plan
    const entry = allowance.left.find((each) => each.kind === kind)
    const about = entry && Number.isFinite(entry.about) ? entry.about : null
    return {
      by: 'plan',
      about,
      used: allowanceUsed(allowance.left) || (about !== null && about <= 0),
      startsAgain: plan.state === 'trial' ? null : allowance.startsAgain,
    }
  }
  if (status?.configured) return { by: 'key' }
  return { by: 'nobody', offered: plan?.state === 'none' || plan?.state === 'ended' }
}

/** Under the buttons of a plan that writes: about how many more of this
 *  kind are left, this month or in the trial. `null` when `about` is. */
export function leftSentence(about: number | null, onTrial: boolean): string | null {
  if (about === null || !Number.isFinite(about)) return null
  const when = onTrial ? 'in the trial' : 'this month'
  return `Enough is left for about ${formatCount(about)} more of these ${when}.`
}

/** Over the copy buttons once the allowance is used: that it is, when it
 *  starts again and that the prompt is here to copy. On a trial, whose
 *  allowance does not start again, the trial's sentence; with a day that
 *  cannot be read, the plan's own sentence of a used allowance. */
export function usedSentence(startsAgain: string | null, now: number): string {
  if (startsAgain === null) return TRIAL_USED
  const again = startsAgainSentence(startsAgain, now)
  return again === null ? ALLOWANCE_USED : `This month's allowance is used. ${again} ${USED_THEN}`
}
