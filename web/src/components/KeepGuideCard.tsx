import type { HandSlotOut, KeepGuideOut, KeyPlayOut } from '../api'
import { percent } from '../theme'
import { Card, Chip, DataTable, Meter, SectionLabel } from './ui'

function IdealHandChips({ idealHand }: { idealHand: HandSlotOut[] }) {
  if (idealHand.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-2">
      {idealHand.map((slot) => (
        <li key={slot.label}>
          <Chip emphasis>
            {slot.count} {slot.label}
          </Chip>
        </li>
      ))}
    </ul>
  )
}

/** One row per opening-hand land count (0..7), the [land_min, land_max] band
 *  picked out in the entity color, everything else in a neutral track —
 *  same "text carries the exact numbers, the bar is the at-a-glance read"
 *  split every other meter in this app already uses (`Meter`, `IntervalBar`,
 *  `TwoSidedMeter`, all in `components/ui/`). */
function LandOddsBars({ keep }: { keep: KeepGuideOut }) {
  const landOdds = keep.land_odds ?? []
  if (landOdds.length === 0) return null
  const { land_min, land_max } = keep
  return (
    <div className="mt-4 space-y-1">
      {landOdds.map(([k, p]) => {
        const inBand = land_min != null && land_max != null && k >= land_min && k <= land_max
        return (
          <div key={k} className="flex items-center gap-2">
            <span className="w-4 text-right text-caption tabular-nums text-muted">{k}</span>
            <Meter
              fraction={p}
              color={inBand ? 's1' : 'muted'}
              height="h-2"
              className="flex-1"
            />
            <span className="w-10 text-right text-caption tabular-nums text-ink2">
              {(p * 100).toFixed(0)}%
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** This deck's own evidence-backed threats and its measured mulligan cost
 *  (`table/keep.py`'s `key_plays` / `mulligan_cost`) — "what this deck
 *  needs" in an opening hand, in the deck's own numbers rather than a
 *  printed curve alone. Both are gated server-side on a minimum decided-game
 *  count, so an empty `key_plays` with no `mulligan_cost` means the deck
 *  doesn't have enough recorded games yet, not that it has no threats. */
function WhatThisDeckNeeds({ keep }: { keep: KeepGuideOut }) {
  const keyPlays = keep.key_plays ?? []
  const cost = keep.mulligan_cost
  if (keyPlays.length === 0 && !cost) return null

  return (
    <div className="mt-4 border-t border-edge pt-3">
      <SectionLabel as="h4">What this deck needs</SectionLabel>
      {keyPlays.length > 0 && (
        <DataTable
          columns={['Key play', 'Best window', 'Record', 'Never resolved']}
          rows={keyPlays.map((kp: KeyPlayOut) => [
            kp.card,
            kp.best_band,
            `${kp.best_band_wins}-${kp.best_band_losses}`,
            `${kp.never_resolved_wins}-${kp.never_resolved_losses}`,
          ])}
        />
      )}
      {cost && (
        <p className="mt-2 text-caption text-ink2">
          Kept 7:{' '}
          <span className="font-medium text-ink">
            {percent(cost.kept_seven_games > 0 ? cost.kept_seven_wins / cost.kept_seven_games : null)}
          </span>{' '}
          ({cost.kept_seven_wins}-{cost.kept_seven_losses} in {cost.kept_seven_games}) vs.
          mulliganed:{' '}
          <span className="font-medium text-ink">
            {percent(cost.mulliganed_games > 0 ? cost.mulliganed_wins / cost.mulliganed_games : null)}
          </span>{' '}
          ({cost.mulliganed_wins}-{cost.mulliganed_losses} in {cost.mulliganed_games}).
        </p>
      )}
    </div>
  )
}

/** What a keepable opening hand looks like for the deck being played, from
 *  its own maindeck curve alone — no board state, so this reads the same
 *  during the mulligan decision as at any later point. `subtitle` carries
 *  this game's own mulligan status (kept / mulliganed N times), which
 *  belongs beside the deck's general mulligan record rather than on its own
 *  card (see CurrentMatchView, which used to put it on a plain scoreboard).
 *
 *  `dense` drops the land-odds bars and the mulligan-record table — the two
 *  tallest blocks, ~220px together — for the closing three-card grid once a
 *  game is under way. The mulligan phase itself always renders full: that is
 *  the one moment this card *is* the screen.
 */
export function KeepGuideCard({
  keep,
  subtitle,
  dense = false,
}: {
  keep: KeepGuideOut | null | undefined
  subtitle?: string
  dense?: boolean
}) {
  if (!keep) return null

  const idealHand = keep.ideal_hand ?? []
  const mulliganRecord = keep.mulligan_record ?? []
  const notes = keep.notes ?? []

  const summary = [
    `${keep.land_count} lands / ${keep.maindeck_size}`,
    keep.avg_mana_value != null ? `avg MV ${keep.avg_mana_value.toFixed(1)}` : null,
    `${keep.creature_count} creatures`,
    `${keep.interaction_count} interaction`,
  ]
    .filter((part): part is string => part != null)
    .join(' · ')

  return (
    <Card title="Keepable seven" subtitle={subtitle} elevation={dense ? 2 : 1}>
      <p className="text-caption text-muted">{summary}</p>
      {keep.untagged_count > 0 && (
        <p className="mt-1 text-caption text-ink2">
          {keep.untagged_count} card{keep.untagged_count === 1 ? '' : 's'} have no rules text on
          file yet, so they are not counted as interaction above.
        </p>
      )}

      {idealHand.length > 0 && (
        <div className="mt-3">
          <IdealHandChips idealHand={idealHand} />
        </div>
      )}

      {keep.keep_rate != null && keep.land_min != null && keep.land_max != null && (
        <p className="mt-3 text-body text-ink2">
          On lands alone, <span className="font-medium text-ink">{percent(keep.keep_rate)}</span>{' '}
          of your opening sevens land in the {keep.land_min}-{keep.land_max} land band.
        </p>
      )}

      {!dense && <LandOddsBars keep={keep} />}

      {!dense && mulliganRecord.length > 0 && (
        <div className="mt-4 border-t border-edge pt-3">
          <SectionLabel as="h4">Mulligan record</SectionLabel>
          <DataTable
            columns={['Hand', 'Games', 'Win rate']}
            rows={mulliganRecord.map((m) => [
              m.mulligans === 0 ? 'Kept 7' : `Mull to ${7 - m.mulligans}`,
              String(m.games),
              percent(m.games > 0 ? m.wins / m.games : null),
            ])}
          />
        </div>
      )}

      {idealHand.length === 0 && notes.length > 0 && (
        <p className="mt-3 text-caption text-muted">{notes[0]}</p>
      )}

      {!dense && <WhatThisDeckNeeds keep={keep} />}
    </Card>
  )
}
