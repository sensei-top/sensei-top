/**
 * The hold lines the Field page's sources section says, as pure functions of
 * the API's `MetaSourceHold`: why a source's fetch is paused or waiting, and
 * when it may run again. The page only draws what `holdLine` returns. The
 * lines are plan 14's catalog (§2), word for word; the CLI's versions of the
 * same rules are `metagame/fetch_lines.py` and `metagame/holds.py`.
 */
import type { MetaSourceHold } from '../api'

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
const WAITING: Record<HoldSource, Record<number, string>> = {
  mtgo: {
    429: 'the site asked for a pause (HTTP 429)',
    503: 'the site answered that it is unavailable (HTTP 503)',
  },
  topdeck: { 429: 'the site asked for a pause (HTTP 429)' },
}

/** What the site did, as a paused line says it. */
const PAUSED: Record<HoldSource, Record<number, string>> = {
  mtgo: {
    403: 'the site refused the fetch (HTTP 403)',
    401: 'the site asked for a login (HTTP 401)',
    451: 'the site refused the fetch for legal reasons (HTTP 451)',
    429: 'the site asked for a pause twice in a row (HTTP 429)',
    503: 'the site has answered that it is unavailable (HTTP 503) for a whole day',
  },
  topdeck: {
    401: 'the key was not accepted (HTTP 401)',
    403: 'the site refused the fetch (HTTP 403)',
    451: 'the site refused the fetch for legal reasons (HTTP 451)',
    429: 'the site asked for a pause twice in a row (HTTP 429)',
  },
}

/** What to do before running `sensei-top meta` again; a 429 has none. */
const ADVICE: Record<HoldSource, Record<number, string>> = {
  mtgo: {
    403: "re-read Daybreak's Terms of Service before you do.",
    401: "Sensei Top never logs in to mtgo.com — re-read Daybreak's Terms of Service before you do.",
    451: 'open mtgo.com in your browser and read the notice there before you do.',
    503: 'check that mtgo.com opens in your browser before you do.',
  },
  topdeck: {
    401: 'set a working key with `sensei-top config --set-topdeck-key KEY` first.',
    403: "re-read TopDeck.gg's API terms before you do.",
    451: 'open topdeck.gg in your browser and read the notice there before you do.',
  },
}

/** The line for a hold that stands, chosen by its cause, or null when the
 *  hold needs no line: none, a wait whose not-before has passed or was never
 *  stored, or a cause with no words. A paused line takes its "and not
 *  before" form only while the not-before is ahead. Every cause `holds.py`
 *  stores has a §2 line, so a cause with none returns null: a fallback
 *  would be wording nobody cleared, and a throw would take the Field page
 *  down. */
export function holdLine(source: HoldSource, hold: MetaSourceHold | null | undefined, now: Date): string | null {
  if (!hold) return null
  const name = NAMES[source]
  if (!name) return null
  const notBefore = hold.not_before ? parse(hold.not_before) : null
  const ahead = notBefore !== null && notBefore.getTime() > now.getTime()
  const cause = hold.http_status
  if (hold.status === 'waiting') {
    const what = WAITING[source]?.[cause]
    if (!what || !ahead) return null
    return `${name} — waiting: ${what}. The next fetch is after ${clock(notBefore, now)}.`
  }
  const what = PAUSED[source]?.[cause]
  if (!what) return null
  const meta = `Nothing more is read until you run \`sensei-top meta\`${ahead ? `, and not before ${clock(notBefore, now)}` : ''}`
  const advice = ADVICE[source]?.[cause]
  const head = `${name} — paused since ${dateOf(parse(hold.since))}: ${what}. ${meta}`
  return advice ? `${head}; ${advice}` : `${head}.`
}
