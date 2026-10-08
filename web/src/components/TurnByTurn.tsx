import { useState } from 'react'
import type { CurrentCardEvent, MatchGame } from '../api'
import { cardName } from '../lib/cards'
import { BoardTable } from './BoardTable'
import { CardImage } from './CardImage'
import { OPENING, TurnScrubber } from './TurnScrubber'
import { Card, CardTile, EmptyState, SectionLabel } from './ui'

/**
 * The turn-by-turn view: one turn at a time, drawn as a table, with a strip
 * of turns to move through the game. The turn is the caller's (the page
 * keeps it in its address); this view keeps only which pile is open, and
 * that closes when the turn changes.
 *
 * Board and log are deliberately separate. The board is *state*: how things
 * stood at the end of that turn. The log is *what happened* during it, so a
 * creature cast that turn is on the board and in the list under it, each
 * for its own reason.
 *
 * A game whose log recorded plays and no board (an MTGO game) has ticks from
 * 1 to its last turn, a sentence in the board's place, and its plays turn by
 * turn.
 */

/** Arena's own categories, the ones worth reading as a play. Everything else
 *  it records (scry moves, spells resolving) stays in the database. */
const PLAYS: Record<string, string> = {
  Draw: 'drew',
  CastSpell: 'cast',
  PlayLand: 'played',
}

/** The opening hand's cards, in px: the board's own card width. */
const OPENING_WIDTH = 64

function EventLine({ event }: { event: CurrentCardEvent }) {
  const name = cardName(event)
  const who = event.is_self === false ? 'Opponent' : event.is_self ? 'You' : 'Someone'
  const verb = PLAYS[event.category ?? ''] ?? event.category ?? 'moved'
  return (
    <li className="flex items-center gap-2 text-body">
      <CardImage
        grpId={event.grp_id}
        name={name}
        className="aspect-[488/680] w-8 shrink-0 rounded-control object-contain"
      />
      <span className="text-ink2">
        <span className="text-ink">{who}</span> {verb} <span className="text-ink">{name}</span>
      </span>
    </li>
  )
}

/** Every tick of a game's strip: the opening hand when the game has one,
 *  then its boards' turns, or, with no board, 1 to the highest of its turn
 *  count and its plays' turns. */
function ticksOf(game: MatchGame, hasOpening: boolean, plays: CurrentCardEvent[]): number[] {
  const turns =
    game.turns.length > 0
      ? game.turns.map((t) => t.turn_number)
      : Array.from(
          { length: Math.max(game.turn_count ?? 0, ...plays.map((p) => p.turn_number ?? 0)) },
          (_, i) => i + 1,
        )
  return hasOpening ? [OPENING, ...turns] : turns
}

export function TurnByTurn({
  game,
  selfSeat,
  turn: requested,
  onTurn,
}: {
  game: MatchGame
  selfSeat: number | null | undefined
  /** The turn the address asks for; null, or a turn the game does not
   *  have, is its last turn. */
  turn: number | null
  onTurn: (turn: number) => void
}) {
  // The open pile, with the turn it was opened on: choosing another turn
  // clears it during render, with no effect to reset it.
  const [pile, setPile] = useState<{ turn: number; key: string } | null>(null)

  const isPlay = (c: CurrentCardEvent) => c.category != null && c.category in PLAYS
  // The opening hand and mulligan put-backs happen before any turn snapshot
  // exists, so they get the strip's leading tick rather than a board.
  const opening = game.cards.filter((c) => c.turn_number == null && isPlay(c))
  const plays = game.cards.filter((c) => c.turn_number != null && isPlay(c))
  const hasBoard = game.turns.length > 0

  if (!hasBoard && plays.length === 0 && opening.length === 0) {
    return (
      <Card title="Turn by turn">
        <EmptyState message="No turns were recorded for this game." />
      </Card>
    )
  }

  const ticks = ticksOf(game, opening.length > 0, plays)
  // The final board is what you usually came for, so no turn is the last.
  const selected = requested != null && ticks.includes(requested) ? requested : (ticks.at(-1) ?? OPENING)
  // Another turn chosen: the pile closes, and stays closed on coming back.
  if (pile != null && pile.turn !== selected) setPile(null)
  const openPile = pile?.turn === selected ? pile.key : null
  const onOpenPile = (key: string | null) => setPile(key == null ? null : { turn: selected, key })

  const index = game.turns.findIndex((t) => t.turn_number === selected)
  const board = index === -1 ? undefined : game.turns[index]
  const prev = index > 0 ? game.turns[index - 1] : undefined
  const events = plays.filter((c) => c.turn_number === selected)

  return (
    <Card
      title="Turn by turn"
      subtitle={
        hasBoard
          ? 'The board at the end of each turn, laid out as on a table: hands on the outside, lands behind, everything else against the line between the two sides. A tapped card is turned sideways.'
          : 'What each player played, turn by turn.'
      }
    >
      <div className="space-y-5">
        <TurnScrubber ticks={ticks} turns={game.turns} selected={selected} onSelect={onTurn} selfSeat={selfSeat} />

        {selected === OPENING ? (
          <div>
            <SectionLabel className="mb-2">Opening hand</SectionLabel>
            <div className="flex flex-wrap items-start gap-1.5">
              {opening.map((event) => (
                <CardTile key={event.seq} grpId={event.grp_id} name={cardName(event)} width={OPENING_WIDTH} />
              ))}
            </div>
          </div>
        ) : !hasBoard ? (
          <p className="text-body text-muted">This game's log recorded what was played, not the board.</p>
        ) : board ? (
          <BoardTable turn={board} prev={prev} selfSeat={selfSeat} openPile={openPile} onOpenPile={onOpenPile} />
        ) : (
          <EmptyState message="No board was recorded for this turn." />
        )}

        {selected !== OPENING && (
          <div>
            <SectionLabel className="mb-2">During turn {selected}</SectionLabel>
            {events.length === 0 ? (
              <p className="text-body text-muted">Nothing visible was drawn, cast or played.</p>
            ) : (
              <ul className="space-y-1.5">
                {events.map((event) => (
                  <EventLine key={event.seq} event={event} />
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
