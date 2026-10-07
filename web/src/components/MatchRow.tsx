import { Link } from 'react-router'
import type { Match } from '../api'
import { eventLabel } from '../lib/events'
import { opponentNamed, ownScore, startOf, UNNAMED_DECK } from '../lib/home'
import { opponentLabelText } from '../lib/opponent'
import { formatDayTime } from '../lib/time'
import { UNKNOWN_OPPONENT_DECK } from './OpponentDeckLabel'
import { Chip, type ChipVariant, ManaPips } from './ui'

const RESULT: Record<string, { word: string; variant: ChipVariant }> = {
  win: { word: 'Win', variant: 'win' },
  loss: { word: 'Loss', variant: 'loss' },
  draw: { word: 'Draw', variant: 'neutral' },
}

// From 48rem up the row is a grid: when, result, opponent's deck, own deck,
// and on Matches the event and rank. Home's four columns are as they were.
// Without the own deck, three: the opponent's deck takes the rest.
const GRID = 'md:grid-cols-[7.5rem_6.5rem_minmax(0,1fr)_minmax(0,11rem)]'
const GRID_WITH_EVENT = 'md:grid-cols-[7.5rem_6.5rem_minmax(0,3fr)_minmax(0,2fr)_minmax(0,2fr)]'
const GRID_WITHOUT_DECK = 'md:grid-cols-[7.5rem_6.5rem_minmax(0,1fr)]'

/** One match, the whole row the way into it; nothing inside it takes a
 *  press of its own. The score puts the viewer's own games first. With
 *  `withEvent` (Matches, not Home) the row ends in one caption: the event
 *  in words, then the rank when there is one. With no event there is no
 *  caption, rank or no rank: the route gives an MTGO match the Arena rank
 *  nearest in time, a row cannot tell its source, and no MTGO match has an
 *  event, so a rank is trusted only beside one. With `withDeck={false}`
 *  the row leaves out the viewer's own deck, column and all: a deck's
 *  Overview is the caller, whose title already names the deck every row
 *  would repeat. No page asks for that together with `withEvent`, and no
 *  grid is built for it. Under 48rem it stacks, that caption last. */
export function MatchRow({
  match,
  withEvent = false,
  withDeck = true,
}: {
  match: Match
  withEvent?: boolean
  withDeck?: boolean
}) {
  const start = startOf(match)
  const result = match.result ? RESULT[match.result] : undefined
  const score = ownScore(match)
  const rank = match.rank_class
    ? `${match.rank_class}${match.rank_level != null ? ` ${match.rank_level}` : ''}`
    : null
  const event = withEvent ? eventLabel(match.event_id) : null
  const eventAndRank = event ? [event, rank].filter(Boolean).join(' · ') : ''
  return (
    <Link
      to={`/matches/${encodeURIComponent(match.match_id)}`}
      className={`-mx-2 flex min-h-[44px] flex-col gap-1 rounded-control px-2 py-2 transition-chrome hover:bg-surface3 md:grid ${
        withEvent ? GRID_WITH_EVENT : withDeck ? GRID : GRID_WITHOUT_DECK
      } md:items-center md:gap-3`}
    >
      <span className="flex flex-wrap items-center gap-2 md:contents">
        <span className="text-caption text-muted tabular-nums">{start != null ? formatDayTime(start) : ''}</span>
        <span>
          {result ? (
            <Chip size="sm" variant={result.variant}>
              {result.word}
              {score && ` ${score}`}
            </Chip>
          ) : (
            <Chip size="sm" muted>
              Not finished
            </Chip>
          )}
        </span>
      </span>
      <OpponentDeck match={match} />
      {withDeck && (
        <span className={`min-w-0 text-caption break-words ${match.deck_name ? 'text-ink2' : 'text-muted'}`}>
          {match.deck_id != null ? (match.deck_name ?? UNNAMED_DECK) : null}
        </span>
      )}
      {eventAndRank && <span className="min-w-0 text-caption break-words text-muted">{eventAndRank}</span>}
    </Link>
  )
}

/** The opponent's deck by name when it was named; a deck known only by
 *  its colours and a card it showed is "Unrecognized deck", with the card
 *  under it; with nothing seen, "Unknown deck". */
function OpponentDeck({ match }: { match: Match }) {
  const named = opponentNamed(match) && match.opponent_label
  const shown = match.opponent_source === 'colors' && match.opponent_label
  return (
    <span className="flex min-w-0 items-center gap-2">
      <ManaPips colors={match.opponent_colors} />
      <span className="min-w-0 break-words">
        {named ? (
          <span className="text-body text-ink">{opponentLabelText(match.opponent_label ?? '', match.opponent_colors)}</span>
        ) : shown ? (
          <>
            <span className="block text-body text-ink">Unrecognized deck</span>
            <span className="block text-caption text-muted">
              showed {opponentLabelText(match.opponent_label ?? '', match.opponent_colors)}
            </span>
          </>
        ) : (
          <span className="text-body text-muted">{UNKNOWN_OPPONENT_DECK}</span>
        )}
      </span>
    </span>
  )
}
