import { Trans, useTranslation } from 'react-i18next'
import type { HandSlotOut, KeepGuideOut, KeyPlayOut } from '../api'
import { formatFixed, formatPercent, formatRecord } from '../lib/format'
import { RATE_MIN_MATCHES, rateAndRecordLine } from '../lib/sample'
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
              {formatPercent(p)}
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
  const { t } = useTranslation()
  const keyPlays = keep.key_plays ?? []
  const cost = keep.mulligan_cost
  if (keyPlays.length === 0 && !cost) return null

  return (
    <div className="mt-4 border-t border-edge pt-3">
      <SectionLabel as="h4">{t('live.keep.needs')}</SectionLabel>
      {keyPlays.length > 0 && (
        <DataTable
          columns={[
            t('live.keep.keyPlay'),
            t('live.keep.bestWindow'),
            t('live.keep.record'),
            t('live.keep.neverResolved'),
          ]}
          rows={keyPlays.map((kp: KeyPlayOut) => [
            kp.card,
            kp.best_band,
            formatRecord(kp.best_band_wins, kp.best_band_losses),
            formatRecord(kp.never_resolved_wins, kp.never_resolved_losses),
          ])}
        />
      )}
      {cost && (
        <p className="mt-2 text-caption text-ink2">
          <Trans
            i18nKey="live.keep.cost"
            values={{
              kept: rateAndRecordLine({ wins: cost.kept_seven_wins, losses: cost.kept_seven_losses }) ?? '—',
              mull: rateAndRecordLine({ wins: cost.mulliganed_wins, losses: cost.mulliganed_losses }) ?? '—',
            }}
            components={{ strong: <span className="font-medium text-ink" /> }}
          />
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
  const { t } = useTranslation()
  if (!keep) return null

  const idealHand = keep.ideal_hand ?? []
  const mulliganRecord = keep.mulligan_record ?? []
  const notes = keep.notes ?? []

  const summary = [
    t('live.keep.lands', { lands: keep.land_count, size: keep.maindeck_size }),
    keep.avg_mana_value != null
      ? t('live.keep.avgMv', { value: formatFixed(keep.avg_mana_value, 1) })
      : null,
    t('live.keep.creatures', { count: keep.creature_count }),
    t('live.keep.interaction', { count: keep.interaction_count }),
  ]
    .filter((part): part is string => part != null)
    .join(' · ')

  return (
    <Card title={t('live.keep.title')} subtitle={subtitle} elevation={dense ? 2 : 1}>
      <p className="text-caption text-muted">{summary}</p>
      {keep.untagged_count > 0 && (
        <p className="mt-1 text-caption text-ink2">
          {t('live.keep.untagged', { count: keep.untagged_count })}
        </p>
      )}

      {idealHand.length > 0 && (
        <div className="mt-3">
          <IdealHandChips idealHand={idealHand} />
        </div>
      )}

      {keep.keep_rate != null && keep.land_min != null && keep.land_max != null && (
        <p className="mt-3 text-body text-ink2">
          <Trans
            i18nKey="live.keep.landBand"
            values={{ rate: formatPercent(keep.keep_rate), min: keep.land_min, max: keep.land_max }}
            components={{ strong: <span className="font-medium text-ink" /> }}
          />
        </p>
      )}

      {!dense && <LandOddsBars keep={keep} />}

      {!dense && mulliganRecord.length > 0 && (
        <div className="mt-4 border-t border-edge pt-3">
          <SectionLabel as="h4">{t('live.keep.mulliganRecord')}</SectionLabel>
          <DataTable
            columns={[t('live.keep.hand'), t('live.keep.games'), t('live.keep.record'), t('live.keep.winRate')]}
            rows={mulliganRecord.map((m) => [
              m.mulligans === 0 ? t('live.keep.kept7') : t('live.keep.mullTo', { n: 7 - m.mulligans }),
              String(m.games),
              formatRecord(m.wins, m.games - m.wins),
              m.games >= RATE_MIN_MATCHES ? (
                formatPercent(m.wins / m.games)
              ) : (
                <span key="rate" className="text-muted">{t('common.sample.tooFewCellGames')}</span>
              ),
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
