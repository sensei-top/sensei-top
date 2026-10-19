import { useTranslation } from 'react-i18next'
import type {
  CurrentMatch,
  IntermissionOut,
  PastBoardingCardOut,
  PastBoardingGameOut,
  PastBoardingOut,
} from '../api'
import { usePasteBrief } from '../api'
import type { TFunction } from '../i18n'
import { seenOpponentCards } from '../lib/brief'
import { cardName } from '../lib/cards'
import { railAlternatives } from '../lib/livePanels'
import { confidenceLabel } from '../lib/opponent'
import { BoardPlan, BriefProvenance, PlayAroundList } from './MatchupBriefCard'
import { CopyPromptCard } from './CopyPromptCard'
import { formatPercent } from '../lib/format'
import { rateAndRecordLine } from '../lib/sample'
import { Card, Chip, Disclosure, EmptyState, Prose, SectionLabel } from './ui'

/** Arena's own `ResultReason_*` spelling, humanised the same way for every
 *  value it sends — the fixture only shows `ResultReason_Concede`
 *  ("concede"), but nothing here assumes that's the only one that exists. */
function humanizeReason(reason: string): string {
  const stripped = reason.replace(/^ResultReason_/, '')
  return stripped.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase()
}

/** "Lost game 1 (concede)." The next game and the opponent are the status
 *  strip's. `won`/`reason`
 *  are dropped when null (rule 4: unknown means no render, never a guess) —
 *  ``won`` is only null when Arena never named a winning team or our own
 *  seat, which leaves nothing honest to say about who won. */
function headline(intermission: IntermissionOut, t: TFunction): string {
  if (intermission.won == null) return t('matchups.sideboard.headline.noResult')
  const game = intermission.game_number
  const reason = intermission.reason ? humanizeReason(intermission.reason) : null
  if (intermission.won) {
    return reason
      ? t('matchups.sideboard.headline.wonReason', { game, reason })
      : t('matchups.sideboard.headline.won', { game })
  }
  return reason
    ? t('matchups.sideboard.headline.lostReason', { game, reason })
    : t('matchups.sideboard.headline.lost', { game })
}

function resultWord(result: string | null | undefined, t: TFunction): string {
  switch (result) {
    case undefined:
    case null:
    case '':
      return t('matchups.sideboard.result.unresolved')
    case 'win':
      return t('matchups.sideboard.result.win')
    case 'loss':
      return t('matchups.sideboard.result.loss')
    case 'draw':
      return t('matchups.sideboard.result.draw')
    default:
      return result
  }
}

/** Never a bare grpId (`lib/cards.ts`'s rule, applied to the differently
 *  named `card` field `PastBoardingCardOut` carries instead of
 *  `card_name`) — plus a dagger flag for a card since cut from the current
 *  75, never dropped (rule 4). */
function pastCardLabel(c: PastBoardingCardOut, t: TFunction): string {
  const name = cardName({ card_name: c.card, grp_id: c.grp_id }, t)
  return c.in_current_75 ? name : `${name}†`
}

function formatDelta(g: PastBoardingGameOut, t: TFunction): string {
  const out = g.board_out.map((c) => `−${c.n} ${pastCardLabel(c, t)}`).join(', ')
  const inn = g.board_in.map((c) => `+${c.n} ${pastCardLabel(c, t)}`).join(', ')
  return [out, inn].filter(Boolean).join(' ')
}

/** One compact line per prior match: the boarding delta (deduplicated when
 *  a later game's board didn't change from the one before it — the common
 *  case, since most Bo3s only reboard once) followed by every game's own
 *  result. */
function pastBoardingLine(entry: PastBoardingOut, t: TFunction): string {
  const deltas: string[] = []
  let last = ''
  for (const g of entry.games) {
    const d = formatDelta(g, t)
    if (d && d !== last) {
      deltas.push(d)
      last = d
    }
  }
  const results = entry.games
    .map((g) => t('matchups.sideboard.gameResult', { n: g.game_number, result: resultWord(g.result, t) }))
    .join(', ')
  return [deltas.join('; '), results].filter(Boolean).join(' · ')
}

function hasCutCard(entries: PastBoardingOut[]): boolean {
  return entries.some((e) =>
    e.games.some((g) => [...g.board_in, ...g.board_out].some((c) => !c.in_current_75))
  )
}

/** "What you boarded last time" — never advice, just a fact from
 *  ``game_decks``. Shown under a written plan when there is one
 *  (``plan_basis === 'exact'``); it *is* the primary content, above any
 *  closest-match plan, when there is not (S4/S8). */
function PastBoardingList({ entries, label }: { entries: PastBoardingOut[]; label: string }) {
  const { t } = useTranslation()
  if (entries.length === 0) return null
  return (
    <div>
      <SectionLabel as="h4">{t('matchups.sideboard.lastTime', { label })}</SectionLabel>
      <ul className="mt-1 space-y-1 text-caption text-ink2">
        {entries.map((entry) => (
          <li key={entry.match_id}>{pastBoardingLine(entry, t)}</li>
        ))}
      </ul>
      <p className="mt-1 text-caption text-muted">
        {hasCutCard(entries) ? t('matchups.sideboard.pastNoteCut') : t('matchups.sideboard.pastNote')}
      </p>
    </div>
  )
}

/** Which archetype `past_boarding` is measured against: the opponent's own
 *  classified archetype when one was named (the status strip names it, so
 *  this says only "this archetype"), otherwise the top alternative, which
 *  the strip never shows (S4 step 5b — "the named archetype and, if there
 *  is none, the top alternative"). */
function pastBoardingLabel(intermission: IntermissionOut, t: TFunction): string {
  if (intermission.opponent?.archetype_key) return t('matchups.sideboard.thisArchetype')
  return intermission.alternatives?.[0]?.label ?? t('matchups.sideboard.thisArchetype')
}

/** "Your games 2–3 against it: 58% · 35–25": this deck's own earlier games
 *  2 and 3 against the opponent's deck (`intermission.postboard_record`),
 *  the rate and the record from ten won or lost, the record alone under
 *  ten (`rateAndRecordLine`). A fact, not advice, so it is drawn whatever
 *  the card's body holds. `null`, no element at all, when the record is
 *  null or holds no game won or lost. */
function postboardLine(intermission: IntermissionOut, t: TFunction): React.ReactNode {
  const record = intermission.postboard_record
  const line = record ? rateAndRecordLine({ wins: record.won, losses: record.lost }) : null
  if (line == null) return null
  return <p className="text-caption text-muted">{t('matchups.sideboard.postboardRecord', { record: line })}</p>
}

/** The primary break-phase card: what to board for the next game, from the
 *  best free tier available (S4's precedence) — an exact written plan, the
 *  closest one already written for a different archetype, this deck's own
 *  past boarding against the archetype, or (last) a prompt to write an
 *  exact plan from. Whichever it draws, the first line under the title
 *  (`postboardLine`) is this deck's own games 2 and 3 against the
 *  opponent's deck, when it has any. Reuses `MatchupBriefCard`'s extracted
 *  `BoardPlan`/`PlayAroundList`/`BriefProvenance` rather than forking
 *  their rendering. */
export function SideboardPlanCard({
  intermission,
  match,
}: {
  intermission: IntermissionOut
  match: CurrentMatch | null
}) {
  const { t } = useTranslation()
  const paste = usePasteBrief()
  const seen = seenOpponentCards(match)
  const title = headline(intermission, t)
  const postboard = postboardLine(intermission, t)
  // `alternatives`/`past_boarding` default to `[]` server-side
  // (Field(default_factory=list)) but the generated type still marks them
  // optional, since a default makes a field un-required in the OpenAPI
  // schema rather than non-nullable.
  const pastBoardingEntries = intermission.past_boarding ?? []
  const pastBoarding =
    pastBoardingEntries.length > 0 ? (
      <PastBoardingList entries={pastBoardingEntries} label={pastBoardingLabel(intermission, t)} />
    ) : null

  if (!intermission.plan && !intermission.prompt) {
    // Nothing to show and nothing to write one from: no opponent named yet
    // (a game 1 conceded before a card was seen), no identity for our own
    // deck, or a match whose format is unknown, which is never read live.
    // Say so rather than render a copy card whose buttons are dead.
    return (
      <Card title={title}>
        <div className="space-y-4">
          {postboard}
          <EmptyState
            message={
              intermission.opponent
                ? t('matchups.sideboard.noPlan')
                : intermission.fmt === null
                  ? t('matchups.sideboard.formatUnknownNoPlan')
                  : t('matchups.sideboard.unclassifiedNoPlan')
            }
          />
          {pastBoarding}
        </div>
      </Card>
    )
  }

  if (!intermission.plan) {
    // No exact and no closest plan — the copy-prompt path MatchupBriefCard
    // already renders for the ordinary in-game brief, mirrored here with the
    // break's own deck_key/archetype_key.
    return (
      <CopyPromptCard
        title={title}
        subtitle={t('matchups.sideboard.noPlanYet')}
        prompt={intermission.prompt}
        importCommand={
          intermission.deck_key && intermission.opponent?.archetype_key
            ? `sensei-top brief --deck "${intermission.deck_key}" ` +
              `--archetype "${intermission.opponent.archetype_key}" --import brief.json`
            : undefined
        }
        save={
          intermission.deck_key && intermission.opponent?.archetype_key
            ? (answer) =>
                paste.mutateAsync({
                  key: intermission.deck_key!,
                  archetypeKey: intermission.opponent!.archetype_key!,
                  answer,
                })
            : undefined
        }
      >
        {postboard ? (
          <div className="space-y-4">
            {postboard}
            {pastBoarding}
          </div>
        ) : (
          pastBoarding
        )}
      </CopyPromptCard>
    )
  }

  const plan = intermission.plan
  const isClosest = intermission.plan_basis === 'closest'
  const closestLabel = intermission.plan_archetype_label ?? plan.archetype_label ?? plan.archetype_key

  return (
    <Card title={title}>
      <div className="space-y-4">
        {postboard}
        {isClosest && pastBoarding}
        {isClosest && (
          <p className="rounded-block border border-warn/40 bg-plane px-3 py-2 text-caption text-warn">
            {t('matchups.sideboard.closest', {
              label: t('matchups.sideboard.thisOpponent'),
              closest: closestLabel,
            })}
          </p>
        )}
        {intermission.stale && (
          <p className="text-caption text-warn">
            <Chip variant="warn">{t('matchups.sideboard.stale')}</Chip>{' '}
            {t('matchups.sideboard.staleMessage')}
          </p>
        )}
        <BoardPlan
          boardIn={plan.board_in}
          boardOut={plan.board_out}
          problems={plan.problems}
          size="large"
          heading={t('matchups.sideboard.boarding')}
        />
        <PlayAroundList playAround={plan.play_around} seen={seen} />
        {!isClosest && pastBoarding}
        <Disclosure summary={t('matchups.sideboard.fullWriteup')}>
          <div className="space-y-3">
            <Prose text={plan.prose} />
            <BriefProvenance brief={plan} />
          </div>
        </Disclosure>
      </div>
    </Card>
  )
}

/** The break-phase rail: the other archetypes with a written plan, each
 *  expandable to its own full plan reusing the same shared pieces as the
 *  primary card. The opponent is the status strip's, so there is no
 *  opponent card here. With nothing to list the rail returns null, and the
 *  caller gives the plan card the full width. */
export function SideboardOpponentRail({
  intermission,
  match,
}: {
  intermission: IntermissionOut
  match: CurrentMatch | null
}) {
  const { t } = useTranslation()
  const seen = seenOpponentCards(match)
  const alternatives = railAlternatives(intermission)
  if (alternatives.length === 0) return null
  return (
    <Card title={t('matchups.sideboard.otherPlans')} elevation={2}>
      <div className="divide-y divide-edge/50">
        {alternatives.map((alt) => (
          <div key={alt.archetype_key} className="py-2">
            <Disclosure
              summary={t('matchups.sideboard.alternative', {
                label: alt.label,
                fit: formatPercent(alt.fit),
                confidence: confidenceLabel(alt.confidence, t),
              })}
            >
              <div className="space-y-3">
                <BoardPlan
                  boardIn={alt.brief.board_in}
                  boardOut={alt.brief.board_out}
                  problems={alt.brief.problems}
                  heading={t('matchups.sideboard.boarding')}
                />
                <PlayAroundList playAround={alt.brief.play_around} seen={seen} />
                <Prose text={alt.brief.prose} />
                <BriefProvenance brief={alt.brief} />
              </div>
            </Disclosure>
          </div>
        ))}
      </div>
    </Card>
  )
}
