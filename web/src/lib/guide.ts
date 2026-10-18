import type { ArchetypeChangeOut, ArchetypeShareOut, CardVerdictOut, Match, MatchupPlanOut, PlanProblemOut } from '../api'
import type { TFunction } from '../i18n'
import { formatFixed, formatPercent, formatRecord } from './format'
import { MIN_TRUSTED_FIELD_SAMPLE } from './sample'
import { archetypeName } from './decks'
import { startOf } from './home'
import { formatCount } from './time'

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
export function guideSections({ written, plans, checklist }: WrittenParts, t: TFunction): GuideSection[] {
  const sections: GuideSection[] = [{ id: 'guide-scope', label: t('decks.guide.sections.scope') }]
  if (written) sections.push({ id: 'guide-how-it-works', label: t('decks.guide.sections.howItWorks') })
  sections.push(
    { id: 'guide-your-play', label: t('decks.guide.sections.yourPlay') },
    { id: 'guide-the-list', label: t('decks.guide.sections.theList') },
    { id: 'guide-the-field', label: t('decks.guide.sections.theField') },
  )
  if (plans) sections.push({ id: 'guide-sideboard-plans', label: t('decks.guide.sections.sideboardPlans') })
  sections.push({ id: 'guide-matchup-coverage', label: t('decks.guide.sections.matchupCoverage') })
  if (checklist) sections.push({ id: 'guide-between-rounds', label: t('decks.guide.sections.betweenRounds') })
  sections.push({ id: 'guide-write', label: t('decks.guide.sections.write') })
  return sections
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
export function problemSentence(
  problem: PlanProblemOut,
  orphan: boolean,
  t: TFunction,
): string {
  const message = problem.message.charAt(0).toUpperCase() + problem.message.slice(1)
  const bracketed = problem.archetype.startsWith('(') && problem.archetype.endsWith(')')
  return orphan && !bracketed ? t('decks.guide.problemOrphan', { archetype: archetypeName(problem.archetype), message }) : message
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

/** A leak's `category` as its chip says it: `review/leaks.py`'s `Category`
 *  (frame, clock, trajectory, role, information, resources, baseline) and
 *  the synthetic `deckbuilding`, each keyed; any other code through
 *  `categoryLabel`. */
export function leakCategoryLabel(category: string, t: TFunction): string {
  switch (category) {
    case 'frame':
      return t('decks.leak.category.frame')
    case 'clock':
      return t('decks.leak.category.clock')
    case 'trajectory':
      return t('decks.leak.category.trajectory')
    case 'role':
      return t('decks.leak.category.role')
    case 'information':
      return t('decks.leak.category.information')
    case 'resources':
      return t('decks.leak.category.resources')
    case 'baseline':
      return t('decks.leak.category.baseline')
    case 'deckbuilding':
      return t('decks.leak.category.deckbuilding')
    default:
      return categoryLabel(category)
  }
}

/** A leak's `gap` (0..1, the win-rate difference with and without the
 *  pattern) as whole percentage points. */
export function gapPoints(gap: number): number {
  return Math.round(gap * 100)
}

/** The phrase a zone reads with, in `zoneLabel`'s sentence: `hand` and
 *  `graveyard` are "in your", `exile` takes no "your", `battlefield` is
 *  "on the". `null` for a zone this does not know. */
function zonePhrase(zone: string, t: TFunction): string | null {
  switch (zone) {
    case 'hand':
      return t('decks.guide.zone.hand')
    case 'graveyard':
      return t('decks.guide.zone.graveyard')
    case 'exile':
      return t('decks.guide.zone.exile')
    case 'battlefield':
      return t('decks.guide.zone.battlefield')
    default:
      return null
  }
}

/** `guide/play.py`'s `_TYPE_BUCKETS`, each in the plural. `null` for a type
 *  this does not know. */
function typePlural(type: string, t: TFunction): string | null {
  switch (type) {
    case 'Creature':
      return t('decks.guide.type.creature')
    case 'Instant':
      return t('decks.guide.type.instant')
    case 'Sorcery':
      return t('decks.guide.type.sorcery')
    case 'Artifact':
      return t('decks.guide.type.artifact')
    case 'Enchantment':
      return t('decks.guide.type.enchantment')
    case 'Planeswalker':
      return t('decks.guide.type.planeswalker')
    case 'Land':
      return t('decks.guide.type.land')
    default:
      return null
  }
}

/** A `zone_curve` combo key (`"graveyard/Instant"`) as "Instants in your
 *  graveyard" — `zone_curve`'s own `"{zone}/{bucket}"` join
 *  (`guide/play.py::zone_curve`) read back apart. A zone or a type this
 *  does not know, or text with no `/` at all, comes back exactly as sent:
 *  every case here is a display choice, never a claim the data is wrong. */
export function zoneLabel(combo: string, t: TFunction): string {
  const slash = combo.indexOf('/')
  if (slash === -1) return combo
  const zone = combo.slice(0, slash)
  const type = combo.slice(slash + 1)
  const phrase = zonePhrase(zone, t)
  const plural = typePlural(type, t)
  if (!phrase || !plural) return combo
  return t('decks.guide.zoneLabel', { type: plural, zone: phrase })
}

/** Each of `TIMING_BUCKETS` (`guide/play.py`'s own bucket names) to the
 *  label it reads on screen; a bucket this does not know as it arrived. */
export function timingLabel(bucket: string, t: TFunction): string {
  switch (bucket) {
    case 'by T4':
      return t('decks.guide.timing.byT4')
    case 'T5-6':
      return t('decks.guide.timing.t56')
    case 'T7-8':
      return t('decks.guide.timing.t78')
    case 'T9+':
      return t('decks.guide.timing.t9')
    case 'never resolved':
      return t('decks.guide.timing.never')
    default:
      return bucket
  }
}

/** A key card timing bucket's win-loss record, wins first, en dash; a dash
 *  alone for a bucket with no games in it at all. */
export function timingRecord(bucket: TimingBucket | undefined): string {
  return bucket ? formatRecord(bucket.w, bucket.l) : '—'
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

/** A list-diff verdict's words (`guide/list_diff.py`'s `correct | add |
 *  trim | cut | flex`) as its row's chip says them: `flex` is a card no
 *  winning list plays, so "Not in the field"; `correct` draws no chip and
 *  is `null`; any word this does not know through `categoryLabel`. */
export function verdictLabel(verdict: string, t: TFunction): string | null {
  switch (verdict) {
    case 'correct':
      return null
    case 'add':
      return t('decks.guide.verdict.add')
    case 'trim':
      return t('decks.guide.verdict.trim')
    case 'cut':
      return t('decks.guide.verdict.cut')
    case 'flex':
      return t('decks.guide.verdict.flex')
    default:
      return categoryLabel(verdict)
  }
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
export function copiesLine(card: CardVerdictOut, t: TFunction): string {
  const n = formatCount(card.yours)
  if (card.consensus_copies == null || card.consensus_share == null) {
    return card.yours === 0 ? t('decks.guide.copies.noneNone') : t('decks.guide.copies.playNone', { n })
  }
  const field = { copies: formatFixed(card.consensus_copies, 1), share: formatPercent(card.consensus_share) }
  return card.yours === 0 ? t('decks.guide.copies.nonePlays', field) : t('decks.guide.copies.playPlays', { n, ...field })
}

/** The sentence under a board's label: how many of its `total` cards
 *  differ from the field. A board of one card, and a board of none, say
 *  so in their own words. */
export function differSentence(differing: number, total: number, t: TFunction): string {
  if (total === 0) return t('decks.guide.differ.noCard')
  if (total === 1) {
    return differing === 0 ? t('decks.guide.differ.singleInLine') : t('decks.guide.differ.singleDiffers')
  }
  const counts = { differing: formatCount(differing), total: formatCount(total) }
  if (differing === 0) return t('decks.guide.differ.none', counts)
  if (differing === 1) return t('decks.guide.differ.one', counts)
  return t('decks.guide.differ.many', counts)
}

/** The summary of the disclosure that holds a board's cards in line with
 *  the field. */
export function inLineSummary(count: number, t: TFunction): string {
  return t('decks.guide.inLine', { count, n: formatCount(count) })
}

/** A share's movement since the reset (-1..1, the share less the share
 *  before it) in percentage points, one decimal, the sign said in words:
 *  "up 14.0 points", "down 3.2 points"; "level" when it rounds to 0.0;
 *  `null` when there is no movement to tell. */
export function movementWords(movement: number | null | undefined, t: TFunction): string | null {
  if (movement == null) return null
  // Level is decided on the number: what one decimal of the points would call zero.
  if (Math.round(Math.abs(movement) * 1000) === 0) return t('decks.guide.movement.level')
  const points = formatFixed(Math.abs(movement) * 100, 1)
  return movement > 0 ? t('decks.guide.movement.up', { points }) : t('decks.guide.movement.down', { points })
}

/** The first caption line under an archetype in the field's table, up to
 *  three parts joined by " · ": the lists counted, under five
 *  (`MIN_TRUSTED_FIELD_SAMPLE`) saying they are too few to trust; the
 *  movement since the reset (`movementWords`), left out when there is
 *  none; and what the reset did to the archetype, left out for `intact` or
 *  no entry in `changes`. */
export function fieldCaption(
  share: ArchetypeShareOut,
  change: ArchetypeChangeOut | null | undefined,
  t: TFunction,
): string {
  const counts = { count: share.decks, n: formatCount(share.decks) }
  const parts = [
    share.decks < MIN_TRUSTED_FIELD_SAMPLE ? t('decks.guide.fieldCaption.tooFew', counts) : t('decks.count.lists', counts),
  ]
  const movement = movementWords(share.movement, t)
  if (movement != null) parts.push(movement)
  if (change?.verdict === 'changed') parts.push(t('decks.guide.fieldCaption.changed'))
  else if (change?.verdict === 'gone') parts.push(t('decks.guide.fieldCaption.gone'))
  return parts.join(' · ')
}
