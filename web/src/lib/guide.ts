import type { ArchetypeChangeOut, ArchetypeShareOut, CardVerdictOut, Match, MatchupPlanOut, PlanProblemOut } from '../api'
import { MIN_TRUSTED_FIELD_SAMPLE, percent } from '../theme'
import { archetypeName } from './decks'
import { startOf } from './home'
import { formatCount } from './time'

/** A no-break space: a count and the word after it never part. */
const NBSP = '\u00a0'

/** One section of the Guide: the id its block carries, the label its link
 *  reads. */
export type GuideSection = { id: string; label: string }

/** What the written guide holds, as the sections read it: `written` a
 *  stored guide; `plans` a stored guide with a plan or a problem;
 *  `checklist` a stored guide with an item between rounds. */
export type WrittenParts = { written: boolean; plans: boolean; checklist: boolean }

/** The Guide's sections in the page's order. A written section is in the
 *  list only when the guide holds something for it, and a section not in
 *  the list is not drawn. */
export function guideSections({ written, plans, checklist }: WrittenParts): GuideSection[] {
  const sections: GuideSection[] = [{ id: 'guide-scope', label: 'Scope' }]
  if (written) sections.push({ id: 'guide-how-it-works', label: 'How it works' })
  sections.push(
    { id: 'guide-your-play', label: 'Your play' },
    { id: 'guide-the-list', label: 'The list' },
    { id: 'guide-the-field', label: 'The field' },
  )
  if (plans) sections.push({ id: 'guide-sideboard-plans', label: 'Sideboard plans' })
  sections.push({ id: 'guide-matchup-coverage', label: 'Matchup coverage' })
  if (checklist) sections.push({ id: 'guide-between-rounds', label: 'Between rounds' })
  sections.push({ id: 'guide-write', label: 'Write and export' })
  return sections
}

/** Where the window stands against the page's two ends: `top` when it is
 *  not scrolled at all, `end` when its foot is within 2 px of the page's,
 *  `null` in between. A page that fits the window is at its `top`. */
export type ScrollEdge = 'top' | 'end' | null

export function scrollEdge(scrollY: number, viewportHeight: number, documentHeight: number): ScrollEdge {
  if (scrollY <= 0) return 'top'
  if (scrollY + viewportHeight >= documentHeight - 2) return 'end'
  return null
}

/** The current section of a scroll spy: the first of `ids` at the page's
 *  top, the last at its end, and between them `observed`, the observer's
 *  own answer. */
export function spyCurrent(ids: readonly string[], observed: string, edge: ScrollEdge): string {
  if (ids.length === 0) return observed
  if (edge === 'top') return ids[0]
  if (edge === 'end') return ids[ids.length - 1]
  return observed
}

/** A row that scrolls sideways, and a link in it, all in px: `rowWidth`
 *  the row's visible width, `scrollWidth` its whole width, `pendingLeft`
 *  where its scroll is going (where it is, when no scroll is in flight),
 *  and the link's `linkLeft` (from the start of the row's content, so
 *  whatever the scroll) and `linkWidth`. */
export type RowScroll = {
  rowWidth: number
  scrollWidth: number
  pendingLeft: number
  linkLeft: number
  linkWidth: number
}

/** Where the row should scroll to bring the link into view: `null` when
 *  the link is already whole inside the row as it stands at
 *  `pendingLeft`, or else the `left` that puts the link in the row's
 *  middle, held between 0 and the row's last scroll position. */
export function rowScrollTarget({ rowWidth, scrollWidth, pendingLeft, linkLeft, linkWidth }: RowScroll): number | null {
  if (linkLeft >= pendingLeft && linkLeft + linkWidth <= pendingLeft + rowWidth) return null
  const centred = linkLeft - (rowWidth - linkWidth) / 2
  return Math.min(Math.max(centred, 0), Math.max(scrollWidth - rowWidth, 0))
}

/** The problems `guide/plans.py` found in the plan against `archetype`,
 *  in the server's order. */
export function ownedProblems(problems: PlanProblemOut[], archetype: string): PlanProblemOut[] {
  return problems.filter((problem) => problem.archetype === archetype)
}

/** The problems no plan owns: those whose archetype names no plan in
 *  `plans` (the `(sideboard)` check among them). Grouped by archetype, the
 *  groups in the order each archetype first appears, and each group's
 *  problems in the server's order. */
export function orphanProblems(problems: PlanProblemOut[], plans: MatchupPlanOut[]): PlanProblemOut[] {
  const planned = new Set(plans.map((plan) => plan.archetype))
  const groups = new Map<string, PlanProblemOut[]>()
  for (const problem of problems) {
    if (planned.has(problem.archetype)) continue
    const group = groups.get(problem.archetype)
    if (group) group.push(problem)
    else groups.set(problem.archetype, [problem])
  }
  return Array.from(groups.values()).flat()
}

/** A problem as its paragraph reads: the server's message, its first
 *  letter a capital. A problem no plan owns (`orphan`) whose archetype is a
 *  name, not a word in brackets like `(sideboard)`, has the archetype's
 *  name and a colon before it. */
export function problemSentence(problem: PlanProblemOut, orphan: boolean): string {
  const message = problem.message.charAt(0).toUpperCase() + problem.message.slice(1)
  const bracketed = problem.archetype.startsWith('(') && problem.archetype.endsWith(')')
  return orphan && !bracketed ? `${archetypeName(problem.archetype)}: ${message}` : message
}

// The shapes of the play evidence, which the API sends as open
// dictionaries: guide/play.py's own JSON.
export type BoardCurveRow = {
  n: number
  hand: number | null
  life: number | null
  lands: number | null
  opp_permanents: number | null
}
export type BoardCurve = { win?: Record<string, BoardCurveRow>; loss?: Record<string, BoardCurveRow> }
export type ZoneCurve = Record<string, { win?: Record<string, number>; loss?: Record<string, number> }>
export type TimingBucket = { w: number; l: number }
export type KeyCardTiming = Record<string, Record<string, TimingBucket>>
export type BoardResult = { games: number; wins: number; losses: number }
export type MulliganRecord = { kept_seven?: BoardResult; mulliganed?: BoardResult }
export type LengthResult = { games: number; median_turns: number | null }
export type GameLength = { win?: LengthResult; loss?: LengthResult }

export const TIMING_BUCKETS = ['by T4', 'T5-6', 'T7-8', 'T9+', 'never resolved']

export const num = (v: number | null | undefined): string => (v == null ? '—' : String(v))

/** Wins and losses recovered from the exact rate leaks.py computed
 *  (`wins / n`, no rounding on that side): the numbers the API already
 *  sent, read back for a sentence, never a count invented for it. */
export function winsOf(rate: number, n: number): number {
  return Math.round(rate * n)
}

/** The turns either side holds, each once, in numeric order (`'10'` after
 *  `'9'`). */
export function turnsOf(
  win: Record<string, unknown> | undefined,
  loss: Record<string, unknown> | undefined,
): string[] {
  return Array.from(new Set([...Object.keys(win ?? {}), ...Object.keys(loss ?? {})])).sort(
    (a, b) => Number(a) - Number(b),
  )
}

/** A leak's `category` (`review/leaks.py`'s `Category`, or the synthetic
 *  `"deckbuilding"`) as a sentence-case chip word: the first letter a
 *  capital, every underscore a space. */
export function categoryLabel(category: string): string {
  const spaced = category.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** A leak's `gap` (0..1, the win-rate difference with and without the
 *  pattern) as whole percentage points. */
export function gapPoints(gap: number): number {
  return Math.round(gap * 100)
}

/** The phrase a zone reads with, in `zoneLabel`'s sentence: `hand` and
 *  `graveyard` are "in your", `exile` takes no "your", `battlefield` is
 *  "on the". */
const ZONE_PHRASES: Record<string, string> = {
  hand: 'in your hand',
  graveyard: 'in your graveyard',
  exile: 'in exile',
  battlefield: 'on the battlefield',
}

/** `guide/play.py`'s `_TYPE_BUCKETS`, each in the plural. */
const TYPE_PLURALS: Record<string, string> = {
  Creature: 'Creatures',
  Instant: 'Instants',
  Sorcery: 'Sorceries',
  Artifact: 'Artifacts',
  Enchantment: 'Enchantments',
  Planeswalker: 'Planeswalkers',
  Land: 'Lands',
}

/** A `zone_curve` combo key (`"graveyard/Instant"`) as "Instants in your
 *  graveyard" — `zone_curve`'s own `"{zone}/{bucket}"` join
 *  (`guide/play.py::zone_curve`) read back apart. A zone or a type this
 *  does not know, or text with no `/` at all, comes back exactly as sent:
 *  every case here is a display choice, never a claim the data is wrong. */
export function zoneLabel(combo: string): string {
  const slash = combo.indexOf('/')
  if (slash === -1) return combo
  const zone = combo.slice(0, slash)
  const type = combo.slice(slash + 1)
  const phrase = ZONE_PHRASES[zone]
  const plural = TYPE_PLURALS[type]
  if (!phrase || !plural) return combo
  return `${plural} ${phrase}`
}

/** Each of `TIMING_BUCKETS` (`guide/play.py`'s own bucket names) to the
 *  label it reads on screen. */
export const TIMING_LABELS: Record<string, string> = {
  'by T4': 'By turn 4',
  'T5-6': 'Turns 5–6',
  'T7-8': 'Turns 7–8',
  'T9+': 'Turn 9 on',
  'never resolved': 'Never',
}

/** A key card timing bucket's win-loss record, wins first, en dash; a dash
 *  alone for a bucket with no games in it at all. */
export function timingRecord(bucket: TimingBucket | undefined): string {
  return bucket ? `${bucket.w}–${bucket.l}` : '—'
}

/** A pattern's own `match_ids_with`, resolved against the match list Home
 *  and the Guide share (`useMatches(undefined, 'all', HOME_MATCH_LIMIT)`):
 *  `rows` newest first by `startOf`, a match with no start after every
 *  match that has one; `missing` the ids the list does not hold. An id
 *  given twice in `ids` becomes one row. */
export function patternMatches(ids: string[], matches: Match[]): { rows: Match[]; missing: string[] } {
  const byId = new Map(matches.map((match) => [match.match_id, match]))
  const seen = new Set<string>()
  const rows: Match[] = []
  const missing: string[] = []
  for (const id of ids) {
    if (seen.has(id)) continue
    seen.add(id)
    const match = byId.get(id)
    if (match) rows.push(match)
    else missing.push(id)
  }
  rows.sort((a, b) => {
    const sa = startOf(a)
    const sb = startOf(b)
    if (sa == null) return sb == null ? 0 : 1
    if (sb == null) return -1
    return sb - sa
  })
  return { rows, missing }
}

const VERDICT_LABELS: Record<string, string> = {
  add: 'Add',
  trim: 'Trim',
  cut: 'Cut',
  flex: 'Not in the field',
}

/** A list-diff verdict's words (`guide/list_diff.py`'s `correct | add |
 *  trim | cut | flex`) as its row's chip says them: `flex` is a card no
 *  winning list plays, so "Not in the field"; `correct` draws no chip and
 *  is `null`; any word this does not know through `categoryLabel`. */
export function verdictLabel(verdict: string): string | null {
  if (verdict === 'correct') return null
  return VERDICT_LABELS[verdict] ?? categoryLabel(verdict)
}

/** A board's cards split in two: `inLine` the cards of verdict `correct`,
 *  `differing` every other; each group in the order given. */
export function listGroups(cards: CardVerdictOut[]): { differing: CardVerdictOut[]; inLine: CardVerdictOut[] } {
  const differing: CardVerdictOut[] = []
  const inLine: CardVerdictOut[] = []
  for (const card of cards) (card.verdict === 'correct' ? inLine : differing).push(card)
  return { differing, inLine }
}

/** A row's caption: what the viewer plays, then what the field plays, its
 *  average copies over the lists that play the card (one decimal) and the
 *  part of the lists that do. A card either field number is missing for
 *  (`flex`) is one no list of the field plays. */
export function copiesLine(card: CardVerdictOut): string {
  const yours = card.yours === 0 ? 'You play none' : `You play ${formatCount(card.yours)}`
  const field =
    card.consensus_copies == null || card.consensus_share == null
      ? 'no list of the field plays it'
      : `the field ${card.consensus_copies.toFixed(1)}, in ${percent(card.consensus_share)} of its lists`
  return `${yours} · ${field}`
}

/** The sentence under a board's label: how many of its `total` cards
 *  differ from the field. A board of one card, and a board of none, say
 *  so in their own words. */
export function differSentence(differing: number, total: number): string {
  if (total === 0) return 'No card.'
  if (total === 1) {
    return differing === 0 ? 'The one card is in line with the field.' : 'The one card differs from the field.'
  }
  const of = `of the ${formatCount(total)}${NBSP}cards`
  if (differing === 0) return `None ${of} differs from the field.`
  if (differing === 1) return `1 ${of} differs from the field.`
  return `${formatCount(differing)} ${of} differ from the field.`
}

/** The summary of the disclosure that holds a board's cards in line with
 *  the field. */
export function inLineSummary(count: number): string {
  return count === 1
    ? 'The one card in line with the field'
    : `The ${formatCount(count)}${NBSP}cards in line with the field`
}

/** A share's movement since the reset (-1..1, the share less the share
 *  before it) in percentage points, one decimal, the sign said in words:
 *  "up 14.0 points", "down 3.2 points"; "level" when it rounds to 0.0;
 *  `null` when there is no movement to tell. */
export function movementWords(movement: number | null | undefined): string | null {
  if (movement == null) return null
  const points = (Math.abs(movement) * 100).toFixed(1)
  if (points === '0.0') return 'level'
  return `${movement > 0 ? 'up' : 'down'} ${points}${NBSP}points`
}

/** The first caption line under an archetype in the field's table, up to
 *  three parts joined by " · ": the lists counted, under five
 *  (`MIN_TRUSTED_FIELD_SAMPLE`) saying they are too few to trust; the
 *  movement since the reset (`movementWords`), left out when there is
 *  none; and what the reset did to the archetype, left out for `intact` or
 *  no entry in `changes`. */
export function fieldCaption(share: ArchetypeShareOut, change: ArchetypeChangeOut | null | undefined): string {
  const lists = `${formatCount(share.decks)}${NBSP}${share.decks === 1 ? 'list' : 'lists'}`
  const parts = [share.decks < MIN_TRUSTED_FIELD_SAMPLE ? `${lists}, too few to trust` : lists]
  const movement = movementWords(share.movement)
  if (movement != null) parts.push(movement)
  if (change?.verdict === 'changed') parts.push('changed at the reset')
  else if (change?.verdict === 'gone') parts.push('gone since the reset')
  return parts.join(' · ')
}
