import { ChevronRight } from 'lucide-react'
import type { MouseEvent, ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router'
import type { CoachSource } from '../../api'
import { FOCUS_SLUG, citationOf, drawerSlug, drawerTeaser, hostOf, readingOrder, reportHeadline } from './coach'
import { type Block, type Inline, parseInline, parseReport } from '../../lib/markdown'
import { Card, SectionLabel, TextLink } from '../../components/ui'
import { type RulesNote, useRulesNote } from '../../lib/noteMarker'
import { RulesNoteChip } from '../notes/RulesNoteChip'
import { RulesNotesProvider } from '../notes/context'

/** An `N<n>` citation: that note's chip, nothing when no provider above
 *  knows it. */
function NoteCite({ n }: { n: string }) {
  const note = useRulesNote(n)
  return note ? <RulesNoteChip note={note} /> : null
}

/** A report's inline tree, drawn. A link's label holds no link, url or
 *  citation (`parseInline` sees to it), so one link never sits inside
 *  another. */
function InlineNodes({ nodes, sources }: { nodes: Inline[]; sources: CoachSource[] }) {
  return (
    <>
      {nodes.map((node, i) => {
        switch (node.kind) {
          case 'text':
            return node.text
          case 'strong':
            return (
              <strong key={i} className="font-semibold text-ink">
                <InlineNodes nodes={node.children} sources={sources} />
              </strong>
            )
          case 'em':
            return (
              <em key={i} className="italic">
                <InlineNodes nodes={node.children} sources={sources} />
              </em>
            )
          case 'code':
            return (
              <code key={i} className="rounded-control bg-plane px-1 py-0.5 text-caption text-ink">
                {node.text}
              </code>
            )
          case 'link':
            return (
              <TextLink key={i} href={node.url}>
                <InlineNodes nodes={node.children} sources={sources} />
              </TextLink>
            )
          case 'url':
            return (
              <TextLink key={i} href={node.url} className="break-all">
                {node.url}
              </TextLink>
            )
          case 'cite': {
            const noteN = /^N(\d+)$/.exec(node.label)
            if (noteN) return <NoteCite key={i} n={noteN[1]} />
            const text = `[${node.label}]`
            const target = citationOf(node.label, sources)
            if (target == null) {
              return (
                <span key={i} className="text-caption text-muted">
                  {text}
                </span>
              )
            }
            return (
              <TextLink key={i} href={target.url} muted className="text-caption" aria-label={target.name}>
                {text}
              </TextLink>
            )
          }
        }
      })}
    </>
  )
}

/** A section's blocks. A subhead takes more space above it than lies
 *  between blocks, none when it opens the card; prose is held to a
 *  reading width. */
function SectionBody({ blocks, sources }: { blocks: Block[]; sources: CoachSource[] }) {
  return (
    <div className="space-y-3">
      {blocks.map((block, i) => {
        if (block.kind === 'subhead') {
          return (
            <h4 key={i} className={`font-display text-lead font-semibold text-ink ${i > 0 ? 'pt-3' : ''}`}>
              <InlineNodes nodes={block.inline} sources={sources} />
            </h4>
          )
        }
        if (block.kind === 'paragraph') {
          return (
            <p key={i} className="break-words text-body text-ink2">
              <InlineNodes nodes={block.inline} sources={sources} />
            </p>
          )
        }
        const items = block.items.map((item, j) => (
          <li key={j} className="break-words">
            <InlineNodes nodes={item} sources={sources} />
          </li>
        ))
        const look = 'space-y-1 pl-5 text-body text-ink2 marker:text-muted'
        return block.ordered ? (
          <ol key={i} start={block.start} className={`list-decimal ${look}`}>
            {items}
          </ol>
        ) : (
          <ul key={i} className={`list-disc ${look}`}>
            {items}
          </ul>
        )
      })}
    </div>
  )
}

/** One entry of the Sources card. A reading entry: its label in a column
 *  of its own, then its title as a link (its url when it has none). A
 *  web page: its title as a
 *  link, its host after it, and the passage it was cited for, when any,
 *  under it. */
function SourceItem({ source }: { source: CoachSource }) {
  const text = source.title || source.url
  const link = (
    <TextLink href={source.url} className={source.title ? '' : 'break-all'}>
      {text}
    </TextLink>
  )
  if (source.kind === 'reading') {
    // The label in a column wide enough for "R18", so every title starts
    // at one x and a long one wraps under itself.
    return (
      <div className="grid grid-cols-[2.5rem_minmax(0,1fr)] items-baseline gap-x-2">
        <span className="text-caption text-muted">{source.label}</span>
        <span className="min-w-0">{link}</span>
      </div>
    )
  }
  const host = hostOf(source.url)
  return (
    <>
      <span className="inline-flex flex-wrap items-baseline gap-x-2">
        {link}
        {host && <span className="text-caption text-muted">{host}</span>}
      </span>
      {source.cited_text && <p className="mt-0.5 text-caption text-muted">{source.cited_text}</p>}
    </>
  )
}

function SourceList({ sources }: { sources: CoachSource[] }) {
  return (
    <ul className="space-y-2 text-body text-ink2">
      {sources.map((source, i) => (
        <li key={i} className="break-words">
          <SourceItem source={source} />
        </li>
      ))}
    </ul>
  )
}

/** The API's resolved sources, in `readingOrder`: the reading entries by
 *  number, then the web pages. Labelled "Reading list" and "From the
 *  web" only when both kinds are present; one kind is a plain list. */
function SourcesBody({ sources }: { sources: CoachSource[] }) {
  const { t } = useTranslation()
  const ordered = readingOrder(sources)
  const reading = ordered.filter((s) => s.kind === 'reading')
  const web = ordered.filter((s) => s.kind !== 'reading')
  if (reading.length === 0 || web.length === 0) return <SourceList sources={ordered} />
  return (
    <div className="space-y-4">
      <div>
        <SectionLabel>{t('coach.sources.reading')}</SectionLabel>
        <div className="mt-1">
          <SourceList sources={reading} />
        </div>
      </div>
      <div>
        <SectionLabel>{t('coach.sources.web')}</SectionLabel>
        <div className="mt-1">
          <SourceList sources={web} />
        </div>
      </div>
    </div>
  )
}

/** Which drawers are open: `useOpenParam`'s answer, kept in `?open=`. */
export type DrawerState = {
  open: Set<string>
  toggle: (slug: string) => void
  setAll: (slugs: string[]) => void
}

/** One drawer of the page: the heading and, while it is closed, one line
 *  of what is inside; the body behind it. Controlled by `state` (the
 *  address), so a link, "Expand all" and a click all say the same thing.
 *  `level` is the heading's, 3 under a report's own heading. */
export function Drawer({
  slug,
  title,
  teaser,
  state,
  level = 3,
  bare = false,
  children,
}: {
  slug: string
  title: string
  teaser: string
  state: DrawerState
  level?: 2 | 3
  /** No border and no shadow: a drawer whose body holds raised cards of
   *  its own. */
  bare?: boolean
  children: ReactNode
}) {
  const open = state.open.has(slug)
  const Heading = `h${level}` as const
  return (
    <details
      id={slug}
      open={open}
      onToggle={(event) => {
        if (event.currentTarget.open !== open) state.toggle(slug)
      }}
      className={`group/drawer scroll-mt-4 rounded-card ${
        bare ? '' : 'border border-edge bg-surface shadow-lift [--art-surface:var(--surface-1)]'
      }`}
    >
      <summary
        className={`grid min-h-[44px] cursor-pointer list-none grid-cols-[auto_minmax(0,1fr)] items-start gap-x-2 select-none [&::-webkit-details-marker]:hidden ${
          bare ? 'py-2' : 'p-5'
        }`}
      >
        <ChevronRight
          size={18}
          aria-hidden
          className="row-span-2 mt-1 shrink-0 text-muted transition-transform group-open/drawer:rotate-90 motion-reduce:transition-none"
        />
        <Heading className="font-display text-title text-ink">{title}</Heading>
        {teaser && <span className="col-start-2 text-caption text-muted group-open/drawer:hidden">{teaser}</span>}
      </summary>
      <div className={bare ? 'pt-2' : 'px-5 pb-5'}>{children}</div>
    </details>
  )
}

/** `smooth` unless the viewer asks for reduced motion. */
function goToDrawer(slug: string) {
  // After the drawer has opened and the page has laid it out.
  window.setTimeout(() => {
    const element = document.getElementById(slug)
    if (!element) return
    const margin = Number.parseFloat(getComputedStyle(element).scrollMarginTop) || 0
    const top = element.getBoundingClientRect().top + window.scrollY - margin
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top, behavior: reduced ? 'auto' : 'smooth' })
  }, 0)
}

/** Opens `slug` (the others keep their state) and scrolls to it. */
function openAndGo(state: DrawerState, slug: string) {
  if (!state.open.has(slug)) state.setAll([...state.open, slug])
  goToDrawer(slug)
}

/** "Expand all", "Collapse all" and a link to each drawer, under the
 *  format control. A link is the page's own address with `?open=` set, so
 *  a new tab opens the same drawer; a plain click opens it in place and
 *  scrolls to it. */
export function DrawerNav({
  drawers,
  state,
}: {
  drawers: { slug: string; title: string }[]
  state: DrawerState
}) {
  const { t } = useTranslation()
  const { pathname, search } = useLocation()
  if (drawers.length === 0) return null
  const hrefFor = (slug: string) => {
    const params = new URLSearchParams(search)
    params.set('open', slug)
    return `${pathname}?${params.toString()}`
  }
  const slugs = drawers.map((d) => d.slug)
  const button =
    'inline-flex min-h-[44px] items-center rounded-control px-2.5 text-caption text-muted transition-chrome hover:text-ink'
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <div className="flex gap-1">
        <button type="button" className={button} onClick={() => state.setAll(slugs)}>
          {t('coach.drawers.expandAll')}
        </button>
        <button type="button" className={button} onClick={() => state.setAll([])}>
          {t('coach.drawers.collapseAll')}
        </button>
      </div>
      <nav aria-label={t('coach.drawers.nav')} className="flex flex-wrap gap-x-1">
        {drawers.map((d) => (
          <a
            key={d.slug}
            href={hrefFor(d.slug)}
            onClick={(event: MouseEvent<HTMLAnchorElement>) => {
              event.preventDefault()
              openAndGo(state, d.slug)
            }}
            className={button}
          >
            {d.title}
          </a>
        ))}
      </nav>
    </div>
  )
}

/** "Top priority this week": the report's one sentence, on top. It links
 *  to the focus-areas drawer when the report has one. */
function HeadlineCard({
  headline,
  sections,
  sources,
  state,
}: {
  headline: string | null | undefined
  sections: ReturnType<typeof parseReport>
  sources: CoachSource[]
  state: DrawerState
}) {
  const { t } = useTranslation()
  const { pathname, search } = useLocation()
  const found = reportHeadline(headline, sections)
  const hasFocus = sections.some((s) => s.title != null && drawerSlug(s.title) === FOCUS_SLUG)
  const params = new URLSearchParams(search)
  params.set('open', FOCUS_SLUG)
  return (
    <Card tone="accent">
      <h3 className="font-display text-title text-ink">{t('coach.headline.title')}</h3>
      {found ? (
        <>
          <p className="mt-2 max-w-prose break-words text-lead text-ink">
            <InlineNodes nodes={parseInline(found.text)} sources={sources} />
          </p>
          {found.fromFocus && <p className="mt-1 text-caption text-muted">{t('coach.headline.fromFocus')}</p>}
        </>
      ) : (
        <p className="mt-2 text-body text-ink2">{t('coach.headline.none')}</p>
      )}
      {hasFocus && (
        <p>
          <TextLink
            href={`${pathname}?${params.toString()}`}
            className="inline-flex min-h-[44px] items-center"
            onClick={(event: MouseEvent<HTMLAnchorElement>) => {
              event.preventDefault()
              openAndGo(state, FOCUS_SLUG)
            }}
          >
            {t('coach.headline.link')}
          </TextLink>
        </p>
      )}
    </Card>
  )
}

/** A coach report as a document: the headline card, then one closed drawer
 *  per `## ` section, titled as the report titled it, its Markdown drawn
 *  (`parseReport`). Text before the first heading stays a card with no
 *  title. A citation such as `[R4]` is a muted link to that reading entry.
 *  The section titled "Sources", in any case, lists `sources` in place of
 *  its own prose when there are any; a report with none keeps its own
 *  text. */
export function CoachReport({
  prose,
  headline,
  sources,
  notes,
  state,
}: {
  prose: string
  headline?: string | null
  sources: CoachSource[]
  notes?: readonly RulesNote[] | null
  state: DrawerState
}) {
  const { t } = useTranslation()
  const sections = parseReport(prose)
  return (
    <RulesNotesProvider notes={notes}>
      <div className="space-y-4">
        <HeadlineCard headline={headline} sections={sections} sources={sources} state={state} />
        {sections.map((section, i) => {
          if (section.title == null) {
            return (
              <Card key={i}>
                <SectionBody blocks={section.blocks} sources={sources} />
              </Card>
            )
          }
          const slug = drawerSlug(section.title)
          const isSources = slug === 'sources'
          return (
            <Drawer
              key={i}
              slug={slug}
              title={section.title}
              teaser={drawerTeaser(section, sources.length, t)}
              state={state}
            >
              {isSources && sources.length > 0 ? (
                <SourcesBody sources={sources} />
              ) : (
                <SectionBody blocks={section.blocks} sources={sources} />
              )}
            </Drawer>
          )
        })}
      </div>
    </RulesNotesProvider>
  )
}
