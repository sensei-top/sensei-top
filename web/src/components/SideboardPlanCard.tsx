import type {
  CurrentMatch,
  IntermissionOpponentOut,
  IntermissionOut,
  PastBoardingCardOut,
  PastBoardingGameOut,
  PastBoardingOut,
} from '../api'
import { cardName } from '../lib/cards'
import { seenOpponentCards } from '../lib/brief'
import { BoardPlan, BriefProvenance, PlayAroundList } from './MatchupBriefCard'
import { CopyPromptCard } from './CopyPromptCard'
import { Card, Chip, Disclosure, EmptyState, Meter, Prose, SectionLabel } from './ui'

/** Arena's own `ResultReason_*` spelling, humanised the same way for every
 *  value it sends — the fixture only shows `ResultReason_Concede`
 *  ("concede"), but nothing here assumes that's the only one that exists. */
function humanizeReason(reason: string): string {
  const stripped = reason.replace(/^ResultReason_/, '')
  return stripped.replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase()
}

/** "Lost game 1 (concede) — board for game 2 vs Boros Aggro." `won`/`reason`
 *  are dropped when null (rule 4: unknown means no render, never a guess) —
 *  ``won`` is only null when Arena never named a winning team or our own
 *  seat, which leaves nothing honest to say about who won. */
function headline(intermission: IntermissionOut): string {
  const label = intermission.opponent?.label ?? 'this opponent'
  const suffix = `board for game ${intermission.next_game} vs ${label}`
  if (intermission.won == null) {
    return suffix.charAt(0).toUpperCase() + suffix.slice(1)
  }
  const verb = intermission.won ? 'Won' : 'Lost'
  const reasonPart = intermission.reason ? ` (${humanizeReason(intermission.reason)})` : ''
  return `${verb} game ${intermission.game_number}${reasonPart} — ${suffix}`
}

function opponentHeaderText(opponent: IntermissionOpponentOut): string {
  if (opponent.source === 'manual') return `You picked: ${opponent.label}`
  return `${opponent.label} · ${opponent.confidence} confidence`
}

const RESULT_WORD: Record<string, string> = { win: 'won', loss: 'lost', draw: 'drew' }

function resultWord(result: string | null | undefined): string {
  if (!result) return 'unresolved'
  return RESULT_WORD[result] ?? result
}

/** Never a bare grpId (`lib/cards.ts`'s rule, applied to the differently
 *  named `card` field `PastBoardingCardOut` carries instead of
 *  `card_name`) — plus a dagger flag for a card since cut from the current
 *  75, never dropped (rule 4). */
function pastCardLabel(c: PastBoardingCardOut): string {
  const name = cardName({ card_name: c.card, grp_id: c.grp_id })
  return c.in_current_75 ? name : `${name}†`
}

function formatDelta(g: PastBoardingGameOut): string {
  const out = g.board_out.map((c) => `−${c.n} ${pastCardLabel(c)}`).join(', ')
  const inn = g.board_in.map((c) => `+${c.n} ${pastCardLabel(c)}`).join(', ')
  return [out, inn].filter(Boolean).join(' ')
}

/** One compact line per prior match: the boarding delta (deduplicated when
 *  a later game's board didn't change from the one before it — the common
 *  case, since most Bo3s only reboard once) followed by every game's own
 *  result. */
function pastBoardingLine(entry: PastBoardingOut): string {
  const deltas: string[] = []
  let last = ''
  for (const g of entry.games) {
    const d = formatDelta(g)
    if (d && d !== last) {
      deltas.push(d)
      last = d
    }
  }
  const results = entry.games.map((g) => `G${g.game_number} ${resultWord(g.result)}`).join(', ')
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
  if (entries.length === 0) return null
  return (
    <div>
      <SectionLabel as="h4">Last time vs {label}</SectionLabel>
      <ul className="mt-1 space-y-1 text-caption text-ink2">
        {entries.map((entry) => (
          <li key={entry.match_id}>{pastBoardingLine(entry)}</li>
        ))}
      </ul>
      <p className="mt-1 text-caption text-muted">
        What you boarded last time — not advice.
        {hasCutCard(entries) && ' † no longer in your current 75.'}
      </p>
    </div>
  )
}

/** Which archetype `past_boarding` is measured against: the opponent's own
 *  classified archetype when one was named, otherwise the top alternative
 *  (S4 step 5b — "the named archetype and, if there is none, the top
 *  alternative"). */
function pastBoardingLabel(intermission: IntermissionOut): string {
  if (intermission.opponent?.archetype_key) return intermission.opponent.label
  return intermission.alternatives?.[0]?.label ?? 'this archetype'
}

/** The primary break-phase card: what to board for the next game, from the
 *  best free tier available (S4's precedence) — an exact written plan, the
 *  closest one already written for a different archetype, this deck's own
 *  past boarding against the archetype, or (last) a prompt to write an
 *  exact plan from. Reuses `MatchupBriefCard`'s extracted `BoardPlan`/
 *  `PlayAroundList`/`BriefProvenance` rather than forking their rendering. */
export function SideboardPlanCard({
  intermission,
  match,
}: {
  intermission: IntermissionOut
  match: CurrentMatch | null
}) {
  const seen = seenOpponentCards(match)
  const title = headline(intermission)
  // `alternatives`/`past_boarding` default to `[]` server-side
  // (Field(default_factory=list)) but the generated type still marks them
  // optional, since a default makes a field un-required in the OpenAPI
  // schema rather than non-nullable.
  const pastBoardingEntries = intermission.past_boarding ?? []
  const pastBoarding =
    pastBoardingEntries.length > 0 ? (
      <PastBoardingList entries={pastBoardingEntries} label={pastBoardingLabel(intermission)} />
    ) : null

  if (!intermission.plan && !intermission.prompt) {
    // Nothing to show and nothing to write one from: no opponent named yet
    // (a game 1 conceded before a card was seen), or no identity for our own
    // deck. Say so rather than render a copy card whose buttons are dead.
    return (
      <Card title={title}>
        <div className="space-y-4">
          <EmptyState
            message={
              intermission.opponent
                ? 'No written plan for this matchup, and nothing to write one from.'
                : 'Opponent not identified yet — no plan to show until a card is seen.'
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
        subtitle="No written plan for this matchup yet."
        prompt={intermission.prompt}
        importCommand={
          intermission.deck_key && intermission.opponent?.archetype_key
            ? `sensei-top brief --deck "${intermission.deck_key}" ` +
              `--archetype "${intermission.opponent.archetype_key}" --import brief.json`
            : undefined
        }
      >
        {pastBoarding}
      </CopyPromptCard>
    )
  }

  const plan = intermission.plan
  const isClosest = intermission.plan_basis === 'closest'
  const closestLabel = intermission.plan_archetype_label ?? plan.archetype_label ?? plan.archetype_key

  return (
    <Card title={title}>
      <div className="space-y-4">
        {isClosest && pastBoarding}
        {isClosest && (
          <p className="rounded-block border border-warn/40 bg-plane px-3 py-2 text-caption text-warn">
            No written plan for {intermission.opponent?.label ?? 'this opponent'} — closest
            written plan: {closestLabel}
          </p>
        )}
        {intermission.stale && (
          <p className="text-caption text-warn">
            <Chip variant="warn">Stale</Chip>{' '}
            The field or your current 75 has moved since this plan was written.
          </p>
        )}
        <BoardPlan
          boardIn={plan.board_in}
          boardOut={plan.board_out}
          problems={plan.problems}
          size="large"
          heading={`Board for game ${intermission.next_game}`}
        />
        <PlayAroundList playAround={plan.play_around} seen={seen} />
        {!isClosest && pastBoarding}
        <Disclosure summary="Full writeup">
          <div className="space-y-3">
            <Prose text={plan.prose} />
            <BriefProvenance brief={plan} />
          </div>
        </Disclosure>
      </div>
    </Card>
  )
}

/** The break-phase rail: who the opponent looks like right now (live read,
 *  not the projected — possibly stale — name), and the other archetypes
 *  with a written plan, each expandable to its own full plan reusing the
 *  same shared pieces as the primary card. */
export function SideboardOpponentRail({
  intermission,
  match,
}: {
  intermission: IntermissionOut
  match: CurrentMatch | null
}) {
  const seen = seenOpponentCards(match)
  const alternatives = intermission.alternatives ?? []
  return (
    <div className="flex flex-col gap-3">
      <Card title="Opponent" elevation={2}>
        {intermission.opponent ? (
          <p className="text-body text-ink">{opponentHeaderText(intermission.opponent)}</p>
        ) : (
          <EmptyState message="Opponent not identified yet." />
        )}
        <p className="mt-2 text-caption text-muted">
          {intermission.cards_seen} cards seen
          {intermission.opponent && ` · ${intermission.opponent.source === 'manual' ? 'your pick' : 'live read'}`}
        </p>
      </Card>

      {alternatives.length > 0 && (
        <Card title="Other written plans" elevation={2}>
          <div className="divide-y divide-edge/50">
            {alternatives.map((alt) => (
              <div key={alt.archetype_key} className="py-2">
                <Disclosure
                  summary={`${alt.label} · ${Math.round(alt.fit * 100)}% fit · ${alt.confidence}`}
                >
                  <div className="space-y-3">
                    <Meter fraction={alt.fit} color="s1" />
                    <BoardPlan
                      boardIn={alt.brief.board_in}
                      boardOut={alt.brief.board_out}
                      problems={alt.brief.problems}
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
      )}
    </div>
  )
}
