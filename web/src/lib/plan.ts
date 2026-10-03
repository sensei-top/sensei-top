/**
 * The plan's sentences, as pure functions of what the shell hands over: a
 * day as the app writes one, the trial's days left, the allowance's
 * percentage and its sentence of reports left, the offer's prices and the
 * computers' limit, and what a press that failed says. A price and a count are the shell's, drawn as they
 * come; nothing here computes one. Every function that counts days takes
 * `now`, so a test needs no clock.
 */
import type { Allowance, ReportKind, Saved } from '../bridge'
import { coachDay } from './coach'
import { formatCount, formatPercent, parseTimestamp } from './time'

/** Under the licence key's field when the shell refused a key and gave
 *  no sentence of its own. */
export const KEY_REFUSED = 'The key was not accepted. Check it against your receipt.'

/** Under the checkout's button or "Manage the plan" when the page did not
 *  open and the shell gave no sentence of its own. */
export const PAGE_NOT_OPENED = 'The page could not be opened. Try again.'

/** Under a computer's row when it was not removed and the shell gave no
 *  sentence of its own. */
export const NOT_REMOVED = 'The computer was not removed. Try again.'

/** The allowance's sentence once nothing of it is left. */
export const ALLOWANCE_USED = 'The allowance is used. Every report still gives you its prompt to copy.'

/** Under the allowance's sentence when it names more than one kind. */
export const ALLOWANCE_EACH = 'Each is instead of the others, not as well.'

/** The order the kinds are named in. */
const KIND_ORDER: readonly ReportKind[] = ['coach', 'guide', 'leaks', 'match']

const KIND_WORDS: Record<ReportKind, { one: string; many: string }> = {
  coach: { one: 'coach report', many: 'coach reports' },
  guide: { one: 'deck guide', many: 'deck guides' },
  leaks: { one: 'leak report', many: 'leak reports' },
  match: { one: 'match report', many: 'match reports' },
}

const DAY_MS = 86_400_000

/** The local midnight of the day `value` names: a bare calendar date
 *  (`YYYY-MM-DD`) read from its own parts, a timestamp in the viewer's
 *  zone. `null` when it reads as neither. */
function dayStart(value: string): number | null {
  const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (parts) return new Date(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3])).getTime()
  const ms = parseTimestamp(value)
  if (ms == null) return null
  const day = new Date(ms)
  return new Date(day.getFullYear(), day.getMonth(), day.getDate()).getTime()
}

/** A day of the plan as the coach writes one: "Sep 27", the year added in
 *  a year other than `now`'s; `null` when it cannot be read. */
export const planDay = coachDay

/** A press whose answer is refused, read as a failure with no sentence
 *  of the shell's own. */
export function answerOf(pressing: Promise<Saved>): Promise<Saved> {
  return pressing.catch((): Saved => ({ ok: false, error: '' }))
}

/** The sentence under a press that failed: the shell's own, or `plain`
 *  when it gave none. `null` for one that worked. */
export function pressFailure(saved: Saved, plain: string): string | null {
  return saved.ok ? null : saved.error.trim() || plain
}

/** Whole days from `now`'s day to the day `ends` names, counted by the
 *  calendar in the viewer's zone: 0 on the day itself, 1 the day before.
 *  `null` when `ends` cannot be read. */
export function daysLeft(ends: string, now: number): number | null {
  const end = dayStart(ends)
  if (end == null) return null
  const today = new Date(now)
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()
  // Rounded, since a day that crosses a change of the clock is 23 or 25 hours.
  return Math.round((end - start) / DAY_MS)
}

/** The trial's days left as a sentence: "4 days of the trial are left. It
 *  ends on Sep 27.", "The trial ends tomorrow, on Sep 27." or "The trial
 *  ends today." A trial whose day has passed while the shell still calls it
 *  one is read as ending today. `null` when `ends` cannot be read. */
export function trialSentence(ends: string, now: number): string | null {
  const days = daysLeft(ends, now)
  const day = planDay(ends, now)
  if (days == null || day == null) return null
  if (days <= 0) return 'The trial ends today.'
  if (days === 1) return `The trial ends tomorrow, on ${day}.`
  return `${days} days of the trial are left. It ends on ${day}.`
}

/** What happens when the trial ends: the day and the amount charged, or,
 *  with `then` `null`, that it was cancelled and nothing is charged. `null`
 *  when the day cannot be read. */
export function trialThenSentence(
  ends: string,
  then: { on: string; amount: string } | null,
  now: number,
): string | null {
  if (then === null) {
    const day = planDay(ends, now)
    return day == null ? null : `The trial was cancelled. It works until ${day} and nothing is charged.`
  }
  const day = planDay(then.on, now)
  return day == null ? null : `On ${day} your card is charged ${then.amount} and the plan starts.`
}

/** A running plan's sentence: how it is paid, when it renews and for how
 *  much, or, with `renews` `null`, that it was cancelled and until when it
 *  works. `null` when the day cannot be read. */
export function activeSentence(
  every: 'month' | 'year',
  renews: { on: string; amount: string } | null,
  until: string,
  now: number,
): string | null {
  if (renews === null) {
    const day = planDay(until, now)
    return day == null ? null : `The plan was cancelled. It works until ${day}.`
  }
  const day = planDay(renews.on, now)
  if (day == null) return null
  const paid = every === 'month' ? 'Paid by the month.' : 'Paid by the year.'
  return `${paid} It renews on ${day} for ${renews.amount}.`
}

/** The part of the allowance left, 0 to 1, from the part used; a part
 *  outside 0 to 1 is held at its end, and one that is not a number reads
 *  as all of it used. */
export function partLeft(used: number): number {
  return Number.isFinite(used) ? 1 - Math.min(1, Math.max(0, used)) : 0
}

/** The failed payment's sentence: until when the plan still works. `null`
 *  when the day cannot be read. */
export function paymentFailedSentence(until: string, now: number): string | null {
  const day = planDay(until, now)
  return day == null ? null : `The plan works until ${day}. Update the card to keep it.`
}

/** The percentage of the allowance left, "62% left", from the part used. */
export function percentLeft(used: number): string {
  return `${formatPercent(partLeft(used))}% left`
}

/** The kinds with some left, in the order coach, guide, leaks, match. */
function kindsLeft(left: Allowance['left']): Allowance['left'] {
  return KIND_ORDER.flatMap((kind) =>
    left.filter((each) => each.kind === kind && Number.isFinite(each.about) && each.about > 0),
  )
}

/** Whether nothing of the allowance is left: no kind has a report left. */
export function allowanceUsed(left: Allowance['left']): boolean {
  return kindsLeft(left).length === 0
}

/** How many kinds the allowance's sentence names. */
export function kindsNamed(left: Allowance['left']): number {
  return kindsLeft(left).length
}

/** What the allowance still writes, as alternatives: "Enough for about 3
 *  coach reports, or about 4 deck guides, or about 40 match reports." A
 *  kind with none left is left out; with none left of any, the sentence
 *  that the allowance is used. The counts are the shell's estimate, drawn
 *  as they come. */
export function allowanceSentence(left: Allowance['left']): string {
  const kinds = kindsLeft(left)
  if (kinds.length === 0) return ALLOWANCE_USED
  const parts = kinds.map(({ kind, about }) => {
    const words = KIND_WORDS[kind]
    return about === 1 ? `about 1 ${words.one}` : `about ${formatCount(about)} ${words.many}`
  })
  return `Enough for ${parts.join(', or ')}.`
}

/** When the allowance starts again, "It starts again on Oct 1.", or
 *  `null` when the day cannot be read. */
export function startsAgainSentence(startsAgain: string, now: number): string | null {
  const day = planDay(startsAgain, now)
  return day == null ? null : `It starts again on ${day}.`
}

/** The offer's two prices, as the shell wrote them: "{by the month} a
 *  month, or {by the year} a year." */
export function pricesSentence(byMonth: string, byYear: string): string {
  return `${byMonth} a month, or ${byYear} a year.`
}

/** The offer's primary button: the trial when one is offered, else
 *  "Subscribe". */
export function offerButton(trialDays: number | null): string {
  return trialDays === null ? 'Subscribe' : `Start the ${trialDays}-day trial`
}

/** The sentence under the trial's button. */
export function trialOfferSentence(trialDays: number): string {
  return `The trial asks for a card. It turns into the plan you pick after ${trialDays} days, and costs nothing if you cancel before then.`
}

/** The sentence under a plan that ended, over the offer. `null` when the
 *  day cannot be read. */
export function endedSentence(on: string, now: number): string | null {
  const day = planDay(on, now)
  return day == null
    ? null
    : `Your plan ended on ${day}. Every report still gives you its prompt to copy, and a key of your own still writes them.`
}

/** The sentence under the computers' title: how many the plan works on. */
export function deviceLimitSentence(limit: number): string {
  return limit === 1
    ? 'The plan works on one computer at a time.'
    : `The plan works on ${formatCount(limit)} computers at a time.`
}
