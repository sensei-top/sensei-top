import { Fragment, useMemo } from 'react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useGuide, useGuideNarrative } from '../api'
import { Button, ErrorNote, Loading } from '../components/ui'
import { MatchupCoverageCard } from '../components/MatchupCoverageCard'
import { ScopeCard } from '../components/guide/ScopeCard'
import { YourPlayCard } from '../components/guide/PlayCard'
import { TheListCard } from '../components/guide/ListCard'
import { FieldCard } from '../components/guide/FieldCard'
import {
  BetweenRoundsCard,
  HowItWorksCard,
  NoWrittenGuide,
  SideboardPlansCard,
} from '../components/guide/WrittenCards'
import { NarrativeAndExport } from '../components/guide/WriteAndExport'
import { SectionNav } from '../components/guide/SectionNav'
import { deckAddress } from '../lib/decks'
import { guideSections } from '../lib/guide'
import { useScrollSpy } from '../lib/scrollSpy'

/** What a section clears when a link brings it to the top, plus 16 px:
 *  under 48rem the shell's sticky header and the strip under it, from
 *  48rem the strip alone. Both heights are read from the DOM by
 *  `SectionNav` (`useStickyHeights`), which writes them on this view's
 *  root as `--guide-header` and `--guide-strip`. From 64rem nothing is
 *  stuck above a section, and the margin keeps the column's own `top-4`
 *  clear of the edge.
 *
 *  The block takes focus when a link brings it to the top (`tabIndex`
 *  -1), and, like the skip link's target, draws no ring: it is a place to
 *  start from, not a control. `!` because the ring's rule in `index.css`
 *  is outside Tailwind's layers, and so beats any utility that is not
 *  important. */
const SECTION_CLASS =
  'scroll-mt-[calc(var(--guide-header,0px)_+_var(--guide-strip,0px)_+_16px)] md:scroll-mt-[calc(var(--guide-strip,0px)_+_16px)] lg:scroll-mt-6 outline-none!'

/** A deck's guide: what its recorded games and the freshest tournament
 *  lists say about it, built again on every read rather than written by
 *  hand. `deckKey` is the deck's key, which the layout found from the
 *  address and which `/api/guide/{key}` takes; the deck whole, every
 *  version of it, whichever version the address chose. The sections are
 *  drawn by `components/guide/`, in the order of `guideSections`, and a
 *  section not in that list is not drawn.
 *
 *  The written sections come from whatever was generated or imported
 *  for this deck. `NarrativeAndExport` offers to write it with Claude
 *  when a credential is configured (`docs/llm.md`), and
 *  otherwise takes an answer pasted into the card (or, in a browser with
 *  no desktop shell, `sensei-top guide --deck KEY --import FILE`). Both land in
 *  the same query, an ordinary one on the heartbeat, so an import from
 *  the terminal shows on the page within a few seconds. While that query
 *  is pending neither a written section nor the callout that says there
 *  is none is drawn. */
export function GuideView({ deckKey }: { deckKey: string }) {
  const { t } = useTranslation()
  const guide = useGuide(deckKey)
  const narrativeResponse = useGuideNarrative(deckKey)
  const response = narrativeResponse.data
  const narrative = response?.status === 'ok' ? (response.guide ?? undefined) : undefined

  const written = narrative != null
  const plans = narrative != null && (narrative.matchups.length > 0 || narrative.problems.length > 0)
  const checklist = narrative != null && narrative.checklist.length > 0
  // Memoized on the three booleans, so the scroll spy subscribes again
  // only when a section comes or goes.
  const sections = useMemo(() => guideSections({ written, plans, checklist }, t), [written, plans, checklist, t])
  const sectionIds = useMemo(() => sections.map((section) => section.id), [sections])

  // Called unconditionally, ahead of every early return below (hooks rule).
  // `ready` (not just the ids) is what makes the effect look again once the
  // guide's own — sometimes very slow — fetch finally resolves and the
  // `#guide-...` sections actually exist.
  const guideReady = !guide.isPending && !guide.error && guide.data != null
  const activeSection = useScrollSpy(sectionIds, guideReady)

  if (guide.isPending) return <Loading />
  if (guide.error) return <ErrorNote error={guide.error} />

  const content: Record<string, ReactNode> = {
    'guide-scope': <ScopeCard guide={guide.data} />,
    'guide-how-it-works': narrative && response && <HowItWorksCard guide={narrative} response={response} />,
    'guide-your-play': <YourPlayCard guide={guide.data} narrative={narrative} />,
    'guide-the-list': <TheListCard guide={guide.data} narrative={narrative} />,
    'guide-the-field': <FieldCard guide={guide.data} />,
    'guide-sideboard-plans': narrative && <SideboardPlansCard guide={narrative} />,
    'guide-matchup-coverage': <MatchupCoverageCard guideKey={deckKey} />,
    'guide-between-rounds': narrative && <BetweenRoundsCard guide={narrative} />,
    'guide-write': <NarrativeAndExport guideKey={deckKey} response={response} />,
  }

  return (
    // The root is the block that holds every section, so the strip, sticky
    // inside it, stays stuck the whole length of the page. From 64rem it is
    // a grid, the sections at the left and the column at the right:
    // `self-start` on the column matters, since a grid or a flex row
    // stretches every item to the tallest one's height by default, which
    // silently defeats `position: sticky` (its box would already span the
    // whole scroll range, leaving nothing to stick).
    <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-6">
      <SectionNav sections={sections} activeId={activeSection} />
      <div className="mt-6 min-w-0 space-y-6 lg:col-start-1 lg:row-start-1 lg:mt-0">
        <p>
          <Button variant="secondary" href={`${deckAddress(deckKey)}/guide/rcq`}>
            {t('decks.guide.prepareRcq')}
          </Button>
        </p>
        {sections.map((section) => (
          <Fragment key={section.id}>
            <div id={section.id} tabIndex={-1} className={SECTION_CLASS}>
              {content[section.id]}
            </div>
            {section.id === 'guide-scope' && response != null && !written && <NoWrittenGuide />}
          </Fragment>
        ))}
      </div>
    </div>
  )
}
