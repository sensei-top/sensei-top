import type { MetagameStatus } from '../../api'
import { ageWords, isStale } from '../../lib/field'
import { formatCount } from '../../lib/time'
import { DataTable, Disclosure, SectionLabel, TextBlock } from '../ui'

/** "Where these numbers come from", closed: the events stored by tier, in
 *  rank order, and the copies set aside, how old the tournament results
 *  are and their window, how many archetype rules and how old (and the
 *  simpler rule when the fallback archive is in use), then the sources'
 *  table and, only when the results or the rules are more than seven days
 *  old or were never downloaded, the commands to download them again. */
export function SourcesDisclosure({ status }: { status: MetagameStatus }) {
  const tiers = status.corpus_events_by_tier
  const total = tiers.a + tiers.b + tiers.c + tiers.d
  const copies = status.corpus_duplicate_events
  const sources = status.corpus_sources ?? []

  const events =
    `${formatCount(total)} tournament events stored: ${formatCount(tiers.a)} paper with 64+ players, ${formatCount(tiers.b)} MTGO challenges, ${formatCount(tiers.c)} MTGO leagues, ${formatCount(tiers.d)} smaller paper.` +
    (copies === 1
      ? ' 1 more was set aside as copies of an event already counted.'
      : copies > 0
        ? ` ${formatCount(copies)} more were set aside as copies of an event already counted.`
        : '')

  const results =
    status.corpus_age_hours == null
      ? 'Tournament results have never been downloaded.'
      : status.corpus_window_days != null
        ? `Tournament results were downloaded ${ageWords(status.corpus_age_hours)} ago, covering ${formatCount(status.corpus_window_days)} days.`
        : `Tournament results were downloaded ${ageWords(status.corpus_age_hours)} ago.`

  const fallback = status.archetype_definitions_url?.includes('/Jiliac/') ?? false
  const rules =
    status.archetype_cache_age_hours == null
      ? 'Archetype rules have never been downloaded.'
      : `${formatCount(status.archetype_files)} archetype rules, downloaded ${ageWords(status.archetype_cache_age_hours)} ago.` +
        (fallback ? ' Decks no rule names are grouped by a simpler rule.' : '')

  const commands = [
    isStale(status.corpus_age_hours) ? 'sensei-top meta' : null,
    isStale(status.archetype_cache_age_hours) ? 'sensei-top archetypes' : null,
  ].filter((command): command is string => command != null)

  return (
    <Disclosure summary="Where these numbers come from">
      <div className="space-y-3 text-body text-ink2">
        <p>{events}</p>
        <p>{results}</p>
        <p>{rules}</p>
        {sources.length > 0 && (
          <div>
            <SectionLabel>Sources</SectionLabel>
            <div className="mt-2">
              {/* One row a source: what it is, the events its last refresh
                  stored, how old that refresh is, and whether it needs, has
                  or lacks a key. */}
              <DataTable
                columns={['Source', 'Events (last refresh)', 'Freshness', 'Status']}
                rows={sources.map((src) => [
                  src.source === 'fbettega'
                    ? 'MTGO + Melee cache'
                    : src.source === 'mtgo'
                      ? 'MTGO.com decklists'
                      : 'TopDeck.gg (RCQs)',
                  String(src.events),
                  src.age_hours != null ? `${(src.age_hours / 24).toFixed(1)}d old` : 'never fetched',
                  src.source === 'fbettega' || src.source === 'mtgo'
                    ? 'needs no key'
                    : src.configured
                      ? src.events > 0
                        ? 'configured'
                        : 'configured, not yet fetched'
                      : 'not configured',
                ])}
              />
            </div>
          </div>
        )}
        {commands.length > 0 && (
          <div className="space-y-2">
            <p>To download them again, run:</p>
            <TextBlock>{commands.join('\n')}</TextBlock>
          </div>
        )}
      </div>
    </Disclosure>
  )
}
