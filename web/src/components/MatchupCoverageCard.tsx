import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useGuideCoverage, useGuideCoveragePrompt, usePasteCoverage } from '../api'
import {
  coverageName,
  coveragePromptNotes,
  coverageStatusWord,
  coverageTiles,
  isCoverageGap,
} from '../lib/brief'
import { pairingAddress } from '../lib/pairing'
import { formatPercent } from '../lib/time'
import { placeById } from '../shell/places'
import { CopyPromptBody } from './CopyPromptCard'
import { Button, Card, Chip, DataTable, EmptyState, ErrorNote, Loading, StatTile, TextLink } from './ui'

/** Which archetypes have a matchup brief (`brief/coverage.py`): every
 *  archetype this deck has met and the field's most played ones, in the
 *  server's order. Three tiles (`coverageTiles`); when a row is missing
 *  or stale, the prompt for every gap at once, fetched only on its press
 *  and drawn in this card with no card of its own; then a row per
 *  archetype, its name a link to its pairing, where that brief's own
 *  prompt is, its status a word on a neutral chip and its share of the
 *  field. With no row, an empty state in the card. A failure to load is
 *  drawn in the card's place. A deck whose format is unknown (`fmt` null)
 *  has no rows and no tiles: one empty state says so. */
export function MatchupCoverageCard({ guideKey }: { guideKey: string }) {
  const { t } = useTranslation()
  const title = t('matchups.coverage.title')
  const subtitle = t('matchups.coverage.subtitle')
  const formatUnknown = t('matchups.brief.formatUnknown')
  const coverage = useGuideCoverage(guideKey)
  const [multiOpen, setMultiOpen] = useState(false)
  const coveragePrompt = useGuideCoveragePrompt(guideKey, multiOpen)
  const paste = usePasteCoverage()

  if (coverage.error) return <ErrorNote error={coverage.error} />
  if (coverage.isPending) {
    return (
      <Card title={title} subtitle={subtitle}>
        <Loading />
      </Card>
    )
  }
  const data = coverage.data

  if (data.fmt === null) {
    return (
      <Card title={title} subtitle={subtitle}>
        <EmptyState
          icon={placeById('decks').icon}
          title={t('matchups.coverage.nothingTitle')}
          message={formatUnknown}
        />
      </Card>
    )
  }

  if (data.rows.length === 0) {
    return (
      <Card title={title} subtitle={subtitle}>
        <EmptyState
          icon={placeById('decks').icon}
          title={t('matchups.coverage.nothingTitle')}
          message={t('matchups.coverage.nothingMessage')}
        />
      </Card>
    )
  }

  const gaps = data.rows.some(isCoverageGap)
  const multi = coveragePrompt.data

  return (
    <Card title={title} subtitle={subtitle}>
      <div className="grid gap-4 md:grid-cols-3">
        {coverageTiles(data, t).map((tile) => (
          <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
        ))}
      </div>

      {gaps && (
        <div className="mt-5">
          {!multiOpen ? (
            <Button variant="secondary" onClick={() => setMultiOpen(true)}>
              {t('matchups.coverage.writeAll')}
            </Button>
          ) : (
            <>
              <p className="text-body text-ink2">{t('matchups.coverage.writeAllHint')}</p>
              <CopyPromptBody
                prompt={multi?.status === 'ok' ? multi.prompt : undefined}
                loading={coveragePrompt.isLoading}
                error={
                  coveragePrompt.error?.message ??
                  (multi?.status === 'format_unknown'
                    ? formatUnknown
                    : multi?.status === 'no_consensus'
                      ? t('matchups.coverage.noneEnough')
                      : multi?.status === 'nothing_missing'
                        ? t('matchups.coverage.allWritten')
                        : undefined)
                }
                importCommand={`sensei-top brief --deck "${guideKey}" --missing --import briefs.json`}
                save={(answer) => paste.mutateAsync({ key: guideKey, answer })}
              >
                {multi &&
                  coveragePromptNotes(multi, data.rows, t).map((note) => (
                    <p key={note} className="mt-2 text-caption text-muted">
                      {note}
                    </p>
                  ))}
              </CopyPromptBody>
            </>
          )}
        </div>
      )}

      <div className="mt-5">
        <DataTable
          columns={[
            t('matchups.coverage.columns.archetype'),
            t('matchups.coverage.columns.brief'),
            t('matchups.coverage.columns.field'),
          ]}
          rows={data.rows.map((row) => [
            // `wrap-anywhere`, not `break-words`: in a table only
            // `overflow-wrap: anywhere` lets a long word shrink the column.
            <div key="archetype" className="min-w-0 wrap-anywhere">
              <TextLink href={pairingAddress(guideKey, `archetype:${row.archetype_key}`)} className="text-body">
                {coverageName(row)}
              </TextLink>
            </div>,
            <Chip key="brief" size="sm">
              {coverageStatusWord(row.status, t)}
            </Chip>,
            <span key="field" className="whitespace-nowrap">
              {row.field_share == null ? '—' : `${formatPercent(row.field_share)}%`}
            </span>,
          ])}
        />
      </div>
    </Card>
  )
}
