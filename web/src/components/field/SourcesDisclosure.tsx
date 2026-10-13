import { useTranslation } from 'react-i18next'
import type { MetagameStatus } from '../../api'
import { ageWords, holdLines, isStale } from '../../lib/field'
import { formatFixed } from '../../lib/format'
import { formatCount } from '../../lib/time'
import { DataTable, Disclosure, Prose, SectionLabel, TextBlock } from '../ui'

/** "Where these numbers come from", closed: the events stored by tier, in
 *  rank order, and the copies set aside, how old the tournament results
 *  are and their window, how many archetype rules and how old (and the
 *  simpler rule when the fallback archive is in use), then the sources'
 *  table, a waiting source's hold line and, only when the results or the
 *  rules are more than seven days old or were never downloaded, the
 *  commands to download them again. */
export function SourcesDisclosure({ status, now }: { status: MetagameStatus; now: number }) {
  const { t } = useTranslation()
  const tiers = status.corpus_events_by_tier
  const total = tiers.a + tiers.b + tiers.c + tiers.d
  const copies = status.corpus_duplicate_events
  const sources = status.corpus_sources ?? []

  const events =
    t('field.sources.events', {
      total: formatCount(total),
      a: formatCount(tiers.a),
      b: formatCount(tiers.b),
      c: formatCount(tiers.c),
      d: formatCount(tiers.d),
    }) + (copies > 0 ? ` ${t('field.sources.copies', { count: copies, n: formatCount(copies) })}` : '')

  const results =
    status.corpus_age_hours == null
      ? t('field.sources.resultsNever')
      : status.corpus_window_days != null
        ? t('field.sources.resultsWindow', {
            count: status.corpus_window_days,
            age: ageWords(status.corpus_age_hours, t),
            n: formatCount(status.corpus_window_days),
          })
        : t('field.sources.results', { age: ageWords(status.corpus_age_hours, t) })

  const fallback = status.archetype_definitions_url?.includes('/Jiliac/') ?? false
  const rules =
    status.archetype_cache_age_hours == null
      ? t('field.sources.rulesNever')
      : t('field.sources.rules', {
          count: status.archetype_files,
          n: formatCount(status.archetype_files),
          age: ageWords(status.archetype_cache_age_hours, t),
        }) + (fallback ? ` ${t('field.sources.rulesFallback')}` : '')

  const commands = [
    isStale(status.corpus_age_hours) ? 'sensei-top meta' : null,
    isStale(status.archetype_cache_age_hours) ? 'sensei-top archetypes' : null,
  ].filter((command): command is string => command != null)

  // A waiting hold's line sits under the table; a paused one is the page's.
  const waiting = holdLines(status, 'waiting', now, t)

  return (
    <Disclosure summary={t('field.sources.summary')}>
      <div className="space-y-3 text-body text-ink2">
        <p>{events}</p>
        <p>{results}</p>
        <p>{rules}</p>
        {sources.length > 0 && (
          <div>
            <SectionLabel>{t('field.sources.sectionLabel')}</SectionLabel>
            <div className="mt-2">
              {/* One row a source: what it is, the events its last refresh
                  stored, how old that refresh is, and whether it needs, has
                  or lacks a key. */}
              <DataTable
                columns={[
                  t('field.sources.columns.source'),
                  t('field.sources.columns.events'),
                  t('field.sources.columns.freshness'),
                  t('field.sources.columns.status'),
                ]}
                rows={sources.map((src) => [
                  src.source === 'fbettega'
                    ? t('field.sources.name.fbettega')
                    : src.source === 'mtgo'
                      ? t('field.sources.name.mtgo')
                      : t('field.sources.name.topdeck'),
                  String(src.events),
                  src.age_hours != null
                    ? t('field.sources.daysOld', {
                        days: formatFixed(src.age_hours / 24, 1),
                      })
                    : t('field.sources.neverFetched'),
                  src.source === 'fbettega' || src.source === 'mtgo'
                    ? t('field.sources.status.needsNoKey')
                    : src.configured
                      ? src.events > 0
                        ? t('field.sources.status.configured')
                        : t('field.sources.status.configuredNotFetched')
                      : t('field.sources.status.notConfigured'),
                ])}
              />
            </div>
          </div>
        )}
        {waiting.map((line) => (
          <Prose key={line} text={line} />
        ))}
        {commands.length > 0 && (
          <div className="space-y-2">
            <p>{t('field.sources.download')}</p>
            <TextBlock>{commands.join('\n')}</TextBlock>
          </div>
        )}
      </div>
    </Disclosure>
  )
}
