/**
 * The hold lines the Field page's sources section says, as pure functions of
 * the API's `MetaSourceHold`: why a source's fetch is paused or waiting, and
 * when it may run again. The page only draws what `holdLine` returns. The
 * lines are plan 14's catalog (§2), word for word; the CLI's versions of the
 * same rules are `metagame/fetch_lines.py` and `metagame/holds.py`.
 */
import type { MetaSourceHold } from '../api'
import type { TFunction } from '../i18n'

/** The fetchers that keep a hold: `mtgo` and `topdeck`. */
export type HoldSource = 'mtgo' | 'topdeck'

const NAMES: Record<HoldSource, string> = { mtgo: 'mtgo.com', topdeck: 'TopDeck.gg' }

const MINUTE = 60_000

const pad = (n: number): string => String(n).padStart(2, '0')

const dateOf = (t: Date): string => `${t.getUTCFullYear()}-${pad(t.getUTCMonth() + 1)}-${pad(t.getUTCDate())}`

/** A stored UTC stamp as the time it names. */
const parse = (stamp: string): Date => new Date(stamp)

/** A time as `HH:MM UTC`, rounded up to the minute, with its date in front
 *  when that date differs from the current UTC date. */
function clock(t: Date, now: Date): string {
  const up = new Date(Math.ceil(t.getTime() / MINUTE) * MINUTE)
  const time = `${pad(up.getUTCHours())}:${pad(up.getUTCMinutes())} UTC`
  return dateOf(up) === dateOf(now) ? time : `${dateOf(up)} ${time}`
}

/** What the site did, as the waiting line says it. */
function waitingWhat(source: HoldSource, cause: number, t: TFunction): string | undefined {
  if (cause === 429) return t('field.holds.waitingWhat.429')
  if (cause === 503 && source === 'mtgo') return t('field.holds.waitingWhat.503')
  return undefined
}

/** What the site did, as a paused line says it. */
function pausedWhat(source: HoldSource, cause: number, t: TFunction): string | undefined {
  if (source === 'mtgo') {
    if (cause === 403) return t('field.holds.pausedWhat.mtgo.403')
    if (cause === 401) return t('field.holds.pausedWhat.mtgo.401')
    if (cause === 451) return t('field.holds.pausedWhat.mtgo.451')
    if (cause === 429) return t('field.holds.pausedWhat.mtgo.429')
    if (cause === 503) return t('field.holds.pausedWhat.mtgo.503')
    return undefined
  }
  if (cause === 401) return t('field.holds.pausedWhat.topdeck.401')
  if (cause === 403) return t('field.holds.pausedWhat.topdeck.403')
  if (cause === 451) return t('field.holds.pausedWhat.topdeck.451')
  if (cause === 429) return t('field.holds.pausedWhat.topdeck.429')
  return undefined
}

/** What to do before running `sensei-top meta` again; a 429 has none. */
function adviceFor(source: HoldSource, cause: number, t: TFunction): string | undefined {
  if (source === 'mtgo') {
    if (cause === 403) return t('field.holds.advice.mtgo.403')
    if (cause === 401) return t('field.holds.advice.mtgo.401')
    if (cause === 451) return t('field.holds.advice.mtgo.451')
    if (cause === 503) return t('field.holds.advice.mtgo.503')
    return undefined
  }
  if (cause === 401) return t('field.holds.advice.topdeck.401')
  if (cause === 403) return t('field.holds.advice.topdeck.403')
  if (cause === 451) return t('field.holds.advice.topdeck.451')
  return undefined
}

/** The line for a hold that stands, chosen by its cause, or null when the
 *  hold needs no line: none, a wait whose not-before has passed or was never
 *  stored, or a cause with no words. A paused line takes its "and not
 *  before" form only while the not-before is ahead. Every cause `holds.py`
 *  stores has a §2 line, so a cause with none returns null: a fallback
 *  would be wording nobody cleared, and a throw would take the Field page
 *  down. */
export function holdLine(
  source: HoldSource,
  hold: MetaSourceHold | null | undefined,
  now: Date,
  t: TFunction,
): string | null {
  if (!hold) return null
  const name = NAMES[source]
  if (!name) return null
  const notBefore = hold.not_before ? parse(hold.not_before) : null
  const ahead = notBefore !== null && notBefore.getTime() > now.getTime()
  const cause = hold.http_status
  if (hold.status === 'waiting') {
    const what = waitingWhat(source, cause, t)
    if (!what || !ahead) return null
    return t('field.holds.waiting', { name, what, when: clock(notBefore, now) })
  }
  const what = pausedWhat(source, cause, t)
  if (!what) return null
  const meta = ahead ? t('field.holds.metaNotBefore', { when: clock(notBefore, now) }) : t('field.holds.meta')
  const advice = adviceFor(source, cause, t)
  const head = t('field.holds.paused', { name, since: dateOf(parse(hold.since)), what, meta })
  return advice ? t('field.holds.pausedAdvice', { head, advice }) : t('field.holds.pausedEnd', { head })
}
