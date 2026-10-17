import { useTranslation } from 'react-i18next'
import type { CoachSource } from '../api'
import { citationOf, hostOf, readingOrder } from '../lib/coach'
import { type Block, type Inline, parseReport } from '../lib/markdown'
import { Card, SectionLabel, TextLink } from './ui'

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
            <h3 key={i} className={`font-display text-lead font-semibold text-ink ${i > 0 ? 'pt-3' : ''}`}>
              <InlineNodes nodes={block.inline} sources={sources} />
            </h3>
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

/** A coach report as a document: one card per `## ` section, titled as
 *  the report titled it (the text before the first heading, when any, in
 *  a card with no title), its Markdown drawn (`parseReport`). A citation
 *  such as `[R4]` is a muted link to that reading entry. The section
 *  titled "Sources", in any case, lists `sources` in place of its own
 *  prose when there are any; a report with none keeps its own text. */
export function CoachReport({ prose, sources }: { prose: string; sources: CoachSource[] }) {
  const sections = parseReport(prose)
  return (
    <div className="space-y-4">
      {sections.map((section, i) => {
        const isSources = section.title?.toLowerCase() === 'sources'
        return (
          <Card key={i} title={section.title ?? undefined}>
            {isSources && sources.length > 0 ? (
              <SourcesBody sources={sources} />
            ) : (
              <SectionBody blocks={section.blocks} sources={sources} />
            )}
          </Card>
        )
      })}
    </div>
  )
}
