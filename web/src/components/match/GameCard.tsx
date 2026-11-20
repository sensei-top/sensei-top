import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { SummaryGameLine } from '../../api'
import { resultWord } from '../../lib/events'
import { Chip, type ChipVariant, SectionLabel, TextLink, Tooltip } from '../ui'

type ResultChip = { variant: ChipVariant; muted?: boolean }

const RESULT: Record<string, ResultChip> = {
  win: { variant: 'win' },
  loss: { variant: 'loss' },
  draw: { variant: 'neutral' },
  incomplete: { variant: 'neutral', muted: true },
}

/** A game with no result, or one not in `RESULT`: muted, as `Incomplete` is. */
const NO_RESULT: ResultChip = { variant: 'neutral', muted: true }

/** A beat's label, wearing its sentence from the summary's
 *  `beat_definitions` as a `Tooltip` when it has one, bare when not. */
export function BeatLabel({ label, definition }: { label: string; definition?: string }) {
  return definition ? (
    <Tooltip tip={definition}>
      <SectionLabel as="span">{label}</SectionLabel>
    </Tooltip>
  ) : (
    <SectionLabel as="span">{label}</SectionLabel>
  )
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-caption text-muted">{term}</dt>
      <dd className="text-body text-ink">{children}</dd>
    </div>
  )
}

/** One game's facts on one row: its result, seat, mulligans, length and
 *  how it ended (a fact not known is not drawn), and the way to its replay. */
export function GameFacts({ game, replayHref }: { game: SummaryGameLine; replayHref: string }) {
  const { t } = useTranslation()
  const result = (game.result ? RESULT[game.result] : undefined) ?? NO_RESULT
  const resultText = (game.result ? resultWord(game.result, t) : undefined) ?? t('matches.result.unknown')
  const reason = game.result_reason_text
  const mulligans = game.self_mulligans
  return (
    <div
      role="group"
      aria-label={t('matches.game.factsLabel', { n: game.game_number })}
      className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5 py-2.5 first:pt-0 last:pb-0"
    >
      <SectionLabel as="h3">{t('matches.game.title', { n: game.game_number })}</SectionLabel>
      <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1.5">
        <Fact term={t('matches.game.result')}>
          <Chip size="sm" variant={result.variant} muted={result.muted}>
            {resultText}
          </Chip>
        </Fact>
        {game.on_play != null && (
          <Fact term={t('matches.game.seat')}>{game.on_play ? t('matches.game.onPlay') : t('matches.game.onDraw')}</Fact>
        )}
        {mulligans != null && (
          <Fact term={t('matches.game.mulligans')}>{mulligans === 0 ? t('matches.game.noMulligans') : String(mulligans)}</Fact>
        )}
        {game.turn_count != null && (
          <Fact term={t('matches.game.length')}>{t('matches.game.turns', { count: game.turn_count, n: game.turn_count })}</Fact>
        )}
        {reason && <Fact term={t('matches.game.ended')}>{`${reason.charAt(0).toUpperCase()}${reason.slice(1)}`}</Fact>}
      </dl>
      <p className="ml-auto text-caption">
        <TextLink href={replayHref}>{t('matches.game.replay', { n: game.game_number })}</TextLink>
      </p>
    </div>
  )
}
