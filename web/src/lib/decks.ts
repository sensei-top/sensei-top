/**
 * What the deck pages read, as pure functions of the API's rows and a clock
 * (`now`, milliseconds since the epoch). A deck is an identity of
 * `/api/guide/decks` (one per deck, however many times its list was
 * edited); a version is a row of `/api/decks` (one per list, its `deck_id`
 * a hash of the list). A deck's address names the identity by its `key`.
 */
import type { Deck, DeckIdentityOut, Match } from '../api'
import type { TFunction } from '../i18n'
import { formatRecord } from './format'
import { versionDays } from './deckOverview'
import { isFinished, startOf } from './home'
import type { RateOrRecord } from './sample'
import { RATE_MIN_MATCHES, ROUGH_RATE_MIN, rateOrRecord } from './sample'
import { ago, formatCount, parseTimestamp } from './time'

/** A key as an address spells it in one segment (a deck's, `guid:…`,
 *  `deck:…`, or an opponent's, `archetype:…`): encoded, but with its colon
 *  written as a colon, since the router writes a relative link's colon bare
 *  and a tab is marked current only when its link and the address are
 *  spelled alike. A colon is legal in a path. */
export function addressSegment(key: string): string {
  return encodeURIComponent(key).replace(/%3A/g, ':')
}

/** A deck's own page: `/decks/` and its key (`addressSegment`). */
export function deckAddress(key: string): string {
  return `/decks/${addressSegment(key)}`
}

/** What an address's `:id` names. */
export type ResolvedDeck = {
  identity: DeckIdentityOut
  /** The id is one of the deck's versions, not its key: an address from
   *  before a deck's address was its key, which the layout sends on to the
   *  deck's own. */
  viaVersion: boolean
}

/** The identity whose key is `id`, else the identity one of whose versions
 *  is `id` (marked so), else `null`. */
export function resolveDeck(id: string | undefined, identities: DeckIdentityOut[]): ResolvedDeck | null {
  if (!id) return null
  const byKey = identities.find((identity) => identity.key === id)
  if (byKey) return { identity: byKey, viaVersion: false }
  const byVersion = identities.find((identity) => identity.deck_ids.includes(id))
  return byVersion ? { identity: byVersion, viaVersion: true } : null
}

/** Where the layout sends an address that names the deck `key` but does
 *  not spell it as `deckAddress` does: one of the deck's versions, as
 *  addresses did before (`/decks/<deck_id>/guide` to `/decks/<key>/guide`),
 *  or the key with its colon as `%3A`, in either case. The page under the
 *  deck is kept; the query string and the hash are the caller's to append.
 *  `null` when `pathname` already spells the deck's own address, so a
 *  redirect never leads to another. */
export function deckRedirect(pathname: string, key: string): string | null {
  const parts = /^\/decks\/([^/]+)(.*)$/.exec(pathname)
  if (parts && parts[1] === addressSegment(key)) return null
  return `${deckAddress(key)}${parts?.[2] ?? ''}`
}

/** The deck's version `/api/decks` says was played last; the identity's
 *  first when none of its versions is listed; `null` with no version. */
export function newestVersion(identity: DeckIdentityOut, versions: Deck[]): string | null {
  const ids = new Set(identity.deck_ids)
  const newest = versions
    .filter((deck) => ids.has(deck.deck_id))
    .sort((a, b) => (parseTimestamp(b.last_played) ?? 0) - (parseTimestamp(a.last_played) ?? 0))[0]
  return newest?.deck_id ?? identity.deck_ids[0] ?? null
}

/** A name run together by its source, spaced: a space between a lower-case
 *  letter and the capital after it ("4c LanternStorm" reads "4c
 *  Lantern Storm"), nothing else changed. For an archetype's name or a
 *  format, never for a name the viewer typed. */
export function archetypeName(name: string): string {
  return name.replace(/(\p{Ll})(\p{Lu})/gu, '$1 $2')
}

const TRADITIONAL = /^Traditional(?=\p{Lu})/u

/** A format in words: `TraditionalStandard` "Standard, best of three", and
 *  so for any `Traditional` prefix; any other value spaced as
 *  `archetypeName` spaces it; `null` when there is none. */
export function formatName(format: string | null | undefined, t: TFunction): string | null {
  if (!format) return null
  if (TRADITIONAL.test(format)) {
    return t('decks.format.bestOfThree', { format: archetypeName(format.replace(TRADITIONAL, '')) })
  }
  return archetypeName(format)
}

/** The line under a deck's title that names it as the field does, "Azure
 *  Kites in the field": only when the guide names an archetype and
 *  its spaced name is not the typed name, case aside. `null` otherwise. */
export function fieldNameLine(
  archetype: string | null | undefined,
  typed: string | null | undefined,
  t: TFunction,
): string | null {
  if (!archetype) return null
  const spaced = archetypeName(archetype)
  if (typed != null && spaced.toLowerCase() === typed.toLowerCase()) return null
  return t('decks.fieldName', { name: spaced })
}

/** The line under a deck's title on its own pages: the format in words and
 *  when it was last played, joined by a middle dot. A part is left out when
 *  it is unknown, never padded with a dash, so the line can be empty. The
 *  deck's record is the strip's under it, not this line's. */
export function deckLine(identity: DeckIdentityOut, now: number, t: TFunction): string {
  const played = ago(identity.last_played, now)
  return [formatName(identity.format, t), played && t('decks.line.lastPlayed', { ago: played })]
    .filter(Boolean)
    .join(' · ')
}

/** A tile's record by the small-sample rule (`rateOrRecord`): from ten
 *  finished matches a rate with its line under it, "58%" and
 *  "win rate · 35–25"; five to nine the rate, `thin`, over "rough win rate ·
 *  6–3, under 10 matches"; both lines say "win rate", which a bare
 *  percentage on a tile does not; one to four
 *  the record as the figure, `thin`, with the "too few" line; none, no
 *  figure. `finished` counts wins and losses, draws aside, so the losses
 *  are `finished - wins`. */
export function deckRecord({ finished, wins }: { finished: number; wins: number }, t: TFunction): RateOrRecord {
  const result = rateOrRecord({ wins, losses: finished - wins }, t)
  if (result.figure === null || (result.thin && finished < ROUGH_RATE_MIN)) return result
  const record = formatRecord(wins, finished - wins)
  return {
    ...result,
    line: result.thin
      ? t('common.sample.roughRateLine', { record, min: RATE_MIN_MATCHES })
      : t('common.sample.rateLine', { record }),
  }
}

/** A tile's line on `/decks` under its record: the format in words, and how
 *  many versions when there are several. `null` with neither. */
export function tileDetail(format: string | null | undefined, versions: number, t: TFunction): string | null {
  // The count and its word never part on a narrow tile: the catalogue's text
  // joins them with a no-break space.
  const parts = [
    formatName(format, t),
    versions > 1 ? t('decks.tile.versions', { count: versions, n: formatCount(versions) }) : null,
  ]
  const line = parts.filter(Boolean).join(' · ')
  return line || null
}

export type DecksTile = {
  key: string
  name: string | null
  /** Finished matches, draws aside: `match_wins + match_losses`. */
  finished: number
  wins: number
  lastPlayed: number | null
  /** The most recently played of the tiles that share this name (two or
   *  more tiles, the same name): the tile wears the "Newest" chip. Always
   *  false for a name no other tile has, and for a shared name no tile of
   *  which has a date. */
  newest: boolean
  /** The whole phrase, "played Sep 3 to 14", for a tile that shares its name
   *  with a newer one: it takes the place of the "last played" phrase, so
   *  two lists of one name tell apart by when they were played. `null`
   *  otherwise, and when the list was played on one day only (or one date
   *  is all there is): a range of one day reads badly in Portuguese, so the
   *  tile keeps "last played". */
  playedRange: string | null
  /** The line with the format and the versions (`tileDetail`). */
  detail: string | null
  /** The deck's newest finished match in `matches`, for its art: a match's
   *  detail is read once, so never one still in progress. `null` when the
   *  list holds none, and no other request is made for it. */
  artMatchId: string | null
}

/** What a name shared by two or more identities marks on each (see
 *  `DecksTile`): the one with the latest `last_played` (the first in
 *  `identities`' order on a tie) is `newest`; the others carry
 *  `playedRange`, by the viewer's own days against `now`, unless their list
 *  was played on one day or has one date. Computed over every identity of
 *  `identities`, keyed by identity key, so `/decks` and Home's tiles read
 *  the same; pass the whole list, never a subset. */
export function sameNameMarks(
  identities: DeckIdentityOut[],
  t: TFunction,
  now: number,
): Map<string, { newest: boolean; playedRange: string | null }> {
  const newestOf = new Map<string, number>()
  const sharing = new Map<string, number>()
  identities.forEach((identity, index) => {
    const name = identity.name
    if (name == null) return
    sharing.set(name, (sharing.get(name) ?? 0) + 1)
    const played = parseTimestamp(identity.last_played)
    if (played == null) return
    const best = newestOf.get(name)
    if (best == null || played > (parseTimestamp(identities[best].last_played) ?? 0)) newestOf.set(name, index)
  })
  const marks = new Map<string, { newest: boolean; playedRange: string | null }>()
  identities.forEach((identity, index) => {
    const shared = identity.name != null && (sharing.get(identity.name) ?? 0) > 1
    const newest = shared && newestOf.get(identity.name as string) === index
    const first = parseTimestamp(identity.first_played)
    const last = parseTimestamp(identity.last_played)
    const oneDay = first == null || last == null || new Date(first).toDateString() === new Date(last).toDateString()
    const range =
      shared && !newest && !oneDay
        ? versionDays({ first_played: identity.first_played, first_seen: null, last_played: identity.last_played }, now, t)
        : null
    marks.set(identity.key, { newest, playedRange: range == null ? null : t('decks.tile.playedRange', { range }) })
  })
  return marks
}

/** One tile per identity, in the order the API answers them (the last
 *  played first); its `newest` and `playedRange` are `sameNameMarks`'. */
export function decksTiles(
  identities: DeckIdentityOut[],
  matches: Match[],
  t: TFunction,
  now: number = Date.now(),
): DecksTile[] {
  const marks = sameNameMarks(identities, t, now)
  const finished = matches
    .filter((match) => isFinished(match) && match.deck_id != null && startOf(match) != null)
    .sort((a, b) => (startOf(b) ?? 0) - (startOf(a) ?? 0))
  return identities.map((identity) => {
    const mark = marks.get(identity.key)
    const ids = new Set(identity.deck_ids)
    return {
      key: identity.key,
      name: identity.name ?? null,
      finished: identity.match_wins + identity.match_losses,
      wins: identity.match_wins,
      lastPlayed: parseTimestamp(identity.last_played),
      newest: mark?.newest ?? false,
      playedRange: mark?.playedRange ?? null,
      detail: tileDetail(identity.format, identity.deck_ids.length, t),
      artMatchId: finished.find((match) => ids.has(match.deck_id ?? ''))?.match_id ?? null,
    }
  })
}
