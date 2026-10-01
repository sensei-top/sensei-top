import { useState } from 'react'
import { useGuideCoverage, useGuideCoveragePrompt } from '../api'
import { coverageName, coveragePromptNotes, coverageStatusWord, coverageTiles, isCoverageGap } from '../lib/brief'
import { pairingAddress } from '../lib/pairing'
import { formatPercent } from '../lib/time'
import { placeById } from '../shell/places'
import { CopyPromptBody } from './CopyPromptCard'
import { Button, Card, Chip, DataTable, EmptyState, ErrorNote, Loading, StatTile, TextLink } from './ui'

const TITLE = 'Matchup coverage'
const SUBTITLE =
  'Which archetypes have a brief: the ones you have met, most met first, then the most played ones you have not. Each opens its matchup, where its brief is.'

/** Which archetypes have a matchup brief (`brief/coverage.py`): every
 *  archetype this deck has met and the field's most played ones, in the
 *  server's order. Three tiles (`coverageTiles`); when a row is missing
 *  or stale, the prompt for every gap at once, fetched only on its press
 *  and drawn in this card with no card of its own; then a row per
 *  archetype, its name a link to its pairing, where that brief's own
 *  prompt is, its status a word on a neutral chip and its share of the
 *  field. With no row, an empty state in the card. A failure to load is
 *  drawn in the card's place. */
export function MatchupCoverageCard({ guideKey }: { guideKey: string }) {
  const coverage = useGuideCoverage(guideKey)
  const [multiOpen, setMultiOpen] = useState(false)
  const coveragePrompt = useGuideCoveragePrompt(guideKey, multiOpen)

  if (coverage.error) return <ErrorNote error={coverage.error} />
  if (coverage.isPending) {
    return (
      <Card title={TITLE} subtitle={SUBTITLE}>
        <Loading />
      </Card>
    )
  }
  const data = coverage.data

  if (data.rows.length === 0) {
    return (
      <Card title={TITLE} subtitle={SUBTITLE}>
        <EmptyState
          icon={placeById('decks').icon}
          title="Nothing to cover yet"
          message="Once you meet a named archetype, or tournament results are downloaded, it is listed here."
        />
      </Card>
    )
  }

  const gaps = data.rows.some(isCoverageGap)
  const multi = coveragePrompt.data

  return (
    <Card title={TITLE} subtitle={SUBTITLE}>
      <div className="grid gap-4 md:grid-cols-3">
        {coverageTiles(data).map((tile) => (
          <StatTile key={tile.label} label={tile.label} value={tile.value} detail={tile.detail} />
        ))}
      </div>

      {gaps && (
        <div className="mt-5">
          {!multiOpen ? (
            <Button variant="secondary" onClick={() => setMultiOpen(true)}>
              Write every missing brief
            </Button>
          ) : (
            <>
              <p className="text-body text-ink2">One prompt writes every brief that is missing or out of date.</p>
              <CopyPromptBody
                prompt={multi?.status === 'ok' ? multi.prompt : undefined}
                loading={coveragePrompt.isLoading}
                error={
                  coveragePrompt.error?.message ??
                  (multi?.status === 'no_consensus'
                    ? 'None of these archetypes has enough tournament lists to write from yet.'
                    : multi?.status === 'nothing_missing'
                      ? 'Every brief is written and up to date.'
                      : undefined)
                }
                importCommand={`sensei-top brief --deck "${guideKey}" --missing --import briefs.json`}
              >
                {multi &&
                  coveragePromptNotes(multi, data.rows).map((note) => (
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
          columns={['Archetype', 'Brief', 'Field']}
          rows={data.rows.map((row) => [
            // `wrap-anywhere`, not `break-words`: in a table only
            // `overflow-wrap: anywhere` lets a long word shrink the column.
            <div key="archetype" className="min-w-0 wrap-anywhere">
              <TextLink href={pairingAddress(guideKey, `archetype:${row.archetype_key}`)} className="text-body">
                {coverageName(row)}
              </TextLink>
            </div>,
            <Chip key="brief" size="sm">
              {coverageStatusWord(row.status)}
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
