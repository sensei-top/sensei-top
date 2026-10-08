import { useEffect, useRef, type KeyboardEvent } from 'react'
import type { CurrentTurn } from '../api'

/**
 * The timeline across a game, a radio group as `Segmented` is: one tick per
 * player-turn, plus a leading tick for the opening hand when the game has
 * one. One tab stop (the chosen tick); the arrow keys move and choose, and
 * stop at the first and the last turn; Home and End go to either end. The
 * chosen tick is said by its surface and its ink.
 *
 * In a game with a board, a bar under each number says whose turn it was
 * and the two lives are under it, and a legend line under the strip says
 * what each means. A game with no board has neither, and no legend.
 */

/** The opening hand's tick. Turn numbers start at 1, so 0 is free. */
export const OPENING = 0

const NEXT_KEYS = new Set(['ArrowRight', 'ArrowDown'])
const PREVIOUS_KEYS = new Set(['ArrowLeft', 'ArrowUp'])

export function TurnScrubber({
  ticks,
  turns,
  selected,
  onSelect,
  selfSeat,
}: {
  /** Every tick, in order: `OPENING` first when the game has an opening
   *  hand, then the turn numbers. */
  ticks: number[]
  /** The game's recorded boards; empty for a game with no board. */
  turns: CurrentTurn[]
  selected: number
  onSelect: (turn: number) => void
  selfSeat: number | null | undefined
}) {
  const list = useRef<HTMLDivElement>(null)
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const byNumber = new Map(turns.map((t) => [t.turn_number, t]))
  const board = turns.length > 0
  const checkedIndex = ticks.indexOf(selected)
  const tabStop = checkedIndex === -1 ? 0 : checkedIndex

  // When the page opens on a turn, bring its tick to the middle of the
  // strip. Only the strip scrolls, never the page.
  useEffect(() => {
    const strip = list.current
    const chosen = strip?.querySelector<HTMLElement>('[aria-checked="true"]')
    if (!strip || !chosen) return
    const outer = strip.getBoundingClientRect()
    const inner = chosen.getBoundingClientRect()
    strip.scrollLeft += inner.left - outer.left - (outer.width - inner.width) / 2
  }, [])

  const mine = (turn: CurrentTurn | undefined) =>
    turn?.active_seat != null && selfSeat != null ? turn.active_seat === selfSeat : null

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let target: number
    if (NEXT_KEYS.has(event.key)) target = Math.min(index + 1, ticks.length - 1)
    else if (PREVIOUS_KEYS.has(event.key)) target = Math.max(index - 1, 0)
    else if (event.key === 'Home') target = 0
    else if (event.key === 'End') target = ticks.length - 1
    else return
    event.preventDefault()
    refs.current[target]?.focus()
    onSelect(ticks[target])
  }

  return (
    <div className="space-y-2">
      {/* `relative` keeps each tick's visually hidden words inside the
          scroller; without it they are laid out against the page and
          widen it. */}
      <div
        ref={list}
        role="radiogroup"
        aria-label="Turns"
        className="relative flex gap-1 overflow-x-auto rounded-block bg-surface2 p-1"
      >
        {ticks.map((tick, index) => {
          const turn = byNumber.get(tick)
          const isMine = mine(turn)
          const checked = index === checkedIndex
          const spoken =
            tick === OPENING ? 'Opening hand'
            : isMine == null ? `Turn ${tick}`
            : isMine ? `Turn ${tick}, your turn`
            : `Turn ${tick}, the opponent's turn`
          return (
            <button
              key={tick}
              ref={(element) => {
                refs.current[index] = element
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              tabIndex={index === tabStop ? 0 : -1}
              onClick={() => onSelect(tick)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={`flex min-h-[44px] min-w-[44px] shrink-0 flex-col items-center justify-center gap-1 rounded-control px-2 py-1.5 transition-chrome ${
                checked ? 'bg-surface3 text-ink' : 'text-ink2 hover:text-ink'
              }`}
            >
              <span aria-hidden className="text-caption font-medium tabular-nums">
                {tick === OPENING ? 'Open' : tick}
              </span>
              <span className="sr-only">{spoken}</span>
              {board && (
                <span
                  aria-hidden
                  className={`h-1 w-full rounded-pill ${
                    tick === OPENING ? 'bg-edge'
                    : isMine == null ? 'bg-muted'
                    : isMine ? 'bg-s1'
                    : 'bg-s2'
                  }`}
                />
              )}
              {turn && (
                <span className="text-chip leading-none tabular-nums text-muted">
                  {turn.self_life ?? '—'}–{turn.opp_life ?? '—'}
                </span>
              )}
            </button>
          )
        })}
      </div>
      {board && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-muted">
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-1 w-4 rounded-pill bg-s1" />
            Your turn
          </span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden className="inline-block h-1 w-4 rounded-pill bg-s2" />
            The opponent's turn
          </span>
          <span>Under each turn: your life, then the opponent's.</span>
        </div>
      )}
    </div>
  )
}
