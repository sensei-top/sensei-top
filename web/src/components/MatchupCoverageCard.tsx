import { useTranslation } from 'react-i18next'
import { useGuideCoverage } from '../api'
import {
  coverageName,
  coverageStatusWord,
  coverageTiles,
  isCoverageGap,
} from '../lib/brief'
import { formatPercent } from '../lib/format'
import { pairingAddress } from '../lib/pairing'
import { placeById } from '../shell/places'
import { useAi } from '../ai/registry'
import { Card, Chip, DataTable, EmptyState, ErrorNote, Loading, StatTile, TextLink } from './ui'

/** Which archetypes have a matchup brief (`ai/brief/coverage.py`): every
 *  archetype this deck has met and the field's most played ones, in the
 *  server's order. With AI features on, three tiles (`coverageTiles`) and,
 *  when a row is missing or stale, the prompt for every gap at once,
 *  fetched only on its press and drawn in this card with no card of its
 *  own; then a row per
 *  archetype, its name a link to its pairing, where that brief's own
 *  prompt is, its status a word on a neutral chip and its share of the
 *  field. With AI features off the tiles, the prompt and the status chip
 *  are not drawn: the archetype list and the Field column remain. With
 *  no row, an empty state in the card. A failure to load is drawn in the
 *  card's place. A deck whose format is unknown (`fmt` null)
 *  has no rows and no tiles: one empty state says so. */
export function MatchupCoverageCard({ guideKey }: { guideKey: string }) {
  const { t } = useTranslation()
  const coverage = useGuideCoverage(guideKey)
  const ai = useAi()
  const title = ai ? t('matchups.coverage.title') : t('matchups.coverage.fieldTitle')
  const subtitle = ai ? t('matchups.coverage.subtitle') : t('matchups.coverage.fieldSubtitle')
  const formatUnknown = ai ? t('matchups.brief.formatUnknown') : t('matchups.coverage.fieldFormatUnknown')

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

  return (
    <Card title={title} subtitle={subtitle}>
      {ai && (
        <div className="grid gap-4 md:grid-cols-3">
          {coverageTiles(data, t).map((tile) => (
            <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
          ))}
        </div>
      )}

      {ai && gaps && (
        <div className="mt-5">
          <ai.CoveragePrompt guideKey={guideKey} rows={data.rows} />
        </div>
      )}

      <div className={ai ? 'mt-5' : undefined}>
        <DataTable
          columns={[
            t('matchups.coverage.columns.archetype'),
            ...(ai ? [t('matchups.coverage.columns.brief')] : []),
            t('matchups.coverage.columns.field'),
          ]}
          rows={data.rows.map((row) => [
            // `wrap-anywhere`, not `break-words`: in a table only
            // `overflow-wrap: anywhere` lets a long word shrink the column.
            <div key="archetype" className="min-w-0 wrap-anywhere">
              <TextLink href={pairingAddress(guideKey, `archetype:${row.archetype_key}`)} className="text-body">
                {coverageName(row, data.rows)}
              </TextLink>
            </div>,
            ...(ai
              ? [
                  <Chip key="brief" size="sm">
                    {coverageStatusWord(row.status, t)}
                  </Chip>,
                ]
              : []),
            <span key="field" className="whitespace-nowrap">
              {row.field_share == null ? '—' : formatPercent(row.field_share)}
            </span>,
          ])}
        />
      </div>
    </Card>
  )
}
