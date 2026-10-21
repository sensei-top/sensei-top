import { Link } from 'react-router'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ReactNode } from 'react'
import type { TFunction } from '../i18n'
import { useFormats, useMtgoPickGroups, useMtgoPickHints } from '../api'
import type { MtgoPickGroup, MtgoPickGroups, MtgoUnsurePick } from '../api'
import { PickGroupCard } from '../components/mtgo/PickGroupCard'
import { Button, EmptyState, ErrorNote, Loading, TextLink } from '../components/ui'
import type { SelectOption } from '../components/ui'
import { mtgoFormatsOf } from '../lib/mtgoPick'
import { matchesWord, resultWords } from '../lib/mtgoPicks'
import { formatCount, formatDayTime, parseTimestamp } from '../lib/time'

/** A section of the page: its heading as an `h2`, the sentence that says
 *  what is in it, then its content. */
function Section({ title, caption, children }: { title: string; caption: string; children: ReactNode }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="space-y-4">
      <div className="space-y-1">
        <h2 id={id} className="font-display text-title text-ink">
          {title}
        </h2>
        <p className="text-caption text-muted">{caption}</p>
      </div>
      {children}
    </section>
  )
}

/** Why a match is in no group, in a muted line. */
function reasonWords(match: MtgoUnsurePick, t: TFunction): string {
  if (match.reason === 'few_cards') {
    return t('mtgo.unsure.fewCards', { count: match.cards_seen, n: formatCount(match.cards_seen) })
  }
  // `no_list`, and a poor fit with no list matching a single card. The
  // route does not say which format found no list, so the line cannot
  // name it.
  if (match.reason === 'low_fit' && match.best) {
    return t('mtgo.unsure.bestList', {
      name: match.best.name?.trim() || t('common.unnamedDeck'),
      matched: formatCount(match.best.cards_matched),
      seen: formatCount(match.cards_seen),
    })
  }
  return t('mtgo.unsure.noFit')
}

/** A match no group takes, as the way into its page, where it is picked one
 *  at a time. */
function UnsureRow({ match, hint }: { match: MtgoUnsurePick; hint: string | null | undefined }) {
  const { t } = useTranslation()
  const start = parseTimestamp(match.started_at)
  const result = resultWords(match, t)
  return (
    <li className="py-1 first:pt-0 last:pb-0">
      <Link
        to={`/matches/${encodeURIComponent(match.match_id)}`}
        className="-mx-2 flex min-h-[44px] flex-col gap-0.5 rounded-control px-2 py-2 transition-chrome hover:bg-surface3"
      >
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-caption text-muted tabular-nums">{start != null ? formatDayTime(start) : ''}</span>
          {result && <span className="text-body text-ink">{result}</span>}
          {match.opponent_name && (
            <span className="min-w-0 break-words text-body text-ink2">{t('mtgo.against', { name: match.opponent_name })}</span>
          )}
        </span>
        <span className="text-caption text-muted">{reasonWords(match, t)}</span>
        {hint && <span className="text-caption text-muted">{t('mtgo.hint', { hint })}</span>}
      </Link>
    </li>
  )
}

/** The three sections, drawn once the groups have answered. The hints are
 *  asked for only from here, so their slower request never holds the groups
 *  back; until they answer, or if they fail, no hint line is drawn. */
function Groups({
  data,
  now,
  formats,
  onConfirmed,
}: {
  data: MtgoPickGroups
  now: number
  formats: readonly SelectOption[]
  onConfirmed: (written: number, list: string) => void
}) {
  const { t } = useTranslation()
  const hints = useMtgoPickHints()
  const [partialOpen, setPartialOpen] = useState(false)
  const sure = data.groups.filter((group) => group.fit === 'sure')
  const partial = data.groups.filter((group) => group.fit === 'partial')

  // Keyed on the group's matches as well as its key, so a group that comes
  // back smaller after a confirm starts again from its own proposal.
  const card = (group: MtgoPickGroup) => (
    <PickGroupCard
      key={`${group.key}:${group.matches.map((match) => match.match_id).join(',')}`}
      group={group}
      hint={hints.data?.groups[group.key]}
      formats={formats}
      now={now}
      onConfirmed={onConfirmed}
    />
  )

  return (
    <>
      {sure.length > 0 && (
        <Section title={t('mtgo.sections.sure.title')} caption={t('mtgo.sections.sure.caption')}>
          {sure.map(card)}
        </Section>
      )}
      {partial.length > 0 && (
        <Section title={t('mtgo.sections.partial.title')} caption={t('mtgo.sections.partial.caption')}>
          <Button variant="quiet" size="sm" aria-expanded={partialOpen} onClick={() => setPartialOpen((v) => !v)}>
            {partialOpen ? t('mtgo.groups.hide') : t('mtgo.groups.show', { count: partial.length, n: formatCount(partial.length) })}
          </Button>
          {partialOpen && partial.map(card)}
        </Section>
      )}
      {data.unsure.length > 0 && (
        <Section title={t('mtgo.sections.unsure.title')} caption={t('mtgo.sections.unsure.caption')}>
          <ul className="divide-y divide-line">
            {data.unsure.map((match) => (
              <UnsureRow key={match.match_id} match={match} hint={hints.data?.unsure[match.match_id]} />
            ))}
          </ul>
        </Section>
      )}
    </>
  )
}

/** Every MTGO match still waiting for a deck, grouped by the saved list that
 *  holds most of the cards played in it: the groups that fit, the
 *  ones close to a list (collapsed), and the matches to pick one at a time.
 *  A confirm refetches the groups, and the line it leaves says what it did. */
export function MtgoPicksView() {
  const { t } = useTranslation()
  const query = useMtgoPickGroups()
  const formatsQuery = useFormats()
  // Only the year matters to a date here; read once, never on a clock.
  const [now] = useState(() => Date.now())
  const [done, setDone] = useState<{ written: number; list: string } | null>(null)

  if (query.isPending) return <Loading />
  if (query.error) return <ErrorNote error={query.error} />
  const data = query.data
  const formats = mtgoFormatsOf(formatsQuery.data).map((format) => ({ value: format, label: format }))

  let body
  if (data.mtgo_matches === 0) {
    body = (
      <EmptyState message={t('mtgo.page.noMatches')} />
    )
  } else if (data.waiting === 0) {
    body = (
      <EmptyState
        message={t('mtgo.page.allDone')}
        action={
          <TextLink href="/" className="inline-flex min-h-[44px] items-center">
            {t('mtgo.page.backHome')}
          </TextLink>
        }
      />
    )
  } else {
    body = (
      <Groups
        data={data}
        now={now}
        formats={formats}
        onConfirmed={(written, list) => setDone({ written, list })}
      />
    )
  }

  return (
    <div className="space-y-8">
      <div className="max-w-3xl space-y-2">
        {data.waiting > 0 && (
          <>
            <p className="text-lead text-ink2">
              {t('mtgo.page.intro')}
            </p>
            <p className="text-body text-ink">
              {t('mtgo.page.waiting', { count: data.waiting, matches: matchesWord(data.waiting, t) })}
            </p>
          </>
        )}
        <p role="status" aria-live="polite" className="text-body text-ink2">
          {done &&
            t('mtgo.page.done', { count: done.written, matches: matchesWord(done.written, t), list: done.list })}
        </p>
      </div>
      {body}
    </div>
  )
}
