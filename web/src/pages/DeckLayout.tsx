import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, NavLink, Outlet, useLocation, useParams, useSearchParams } from 'react-router'
import { useAi } from '../ai/registry'
import { useDecks, useGuide, useGuideDecks } from '../api'
import type { TFunction } from '../i18n'
import { DeckKeyNumbers, StripFrames } from '../components/DeckKeyNumbers'
import { BackLink, Button, EmptyState, ErrorNote, OutlineCard, Skeleton } from '../components/ui'
import { chosenVersion } from '../lib/deckOverview'
import { deckLine, deckRedirect, fieldNameLine, newestVersion, resolveDeck } from '../lib/decks'
import { useNow } from '../lib/time'
import { DeckOverviewFrames } from '../views/DeckOverviewView'
import { GuidePending } from '../views/GuideView'
import { MatchupsFrames } from '../views/MatchupsView'
import { PairingOutline } from '../views/PairingView'

/** The deck's tabs. Overview and Matchups read the version the address
 *  chose, so their links keep it; the Guide and RCQ read the deck whole,
 *  and their links drop it. */
function deckTabs(t: TFunction) {
  return [
    { to: '.', label: t('decks.layout.tabs.overview'), end: true, keepsVersion: true },
    { to: 'matchups', label: t('decks.layout.tabs.matchups'), end: false, keepsVersion: true },
    { to: 'guide', label: t('decks.layout.tabs.guide'), end: false, keepsVersion: false },
    { to: 'rcq', label: t('decks.layout.tabs.rcq'), end: false, keepsVersion: false },
  ]
}

/** The tab row, drawn the same pending and loaded. */
function DeckTabs({ versionSearch }: { versionSearch: string }) {
  const { t } = useTranslation()
  return (
    <nav aria-label={t('decks.layout.nav')} className="flex flex-wrap gap-1 pt-1">
      {deckTabs(t).map((tab) => (
        // NavLink marks the current one with aria-current="page" itself.
        <NavLink
          key={tab.label}
          // The search is its own part of the link: NavLink marks a tab by
          // its path alone, so Overview's `end` holds with it.
          to={{ pathname: tab.to, search: tab.keepsVersion ? versionSearch : '' }}
          end={tab.end}
          className={({ isActive }) =>
            `rounded-control px-3 py-1.5 text-caption font-medium transition-chrome ${
              isActive ? 'bg-surface3 text-ink' : 'text-muted hover:text-ink'
            }`
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}

/** The versions the Overview's outline reserves for a deck not yet known. */
const UNKNOWN_VERSIONS = 4

/** The frames of the page under the tabs while the layout waits, chosen by
 *  the address after the deck's own (the Guide and RCQ share one frame):
 *  the page's own pending state, as it will draw it, with the version row
 *  reserved when the deck has several versions or is not known yet.
 *  `deckKey` is `null` until the deck is resolved; the brief waits for it. */
function BodyFrames({ deckKey, deckIds }: { deckKey: string | null; deckIds: string[] | undefined }) {
  const { t } = useTranslation()
  const { id, opponent = '' } = useParams()
  const ai = useAi()
  const { pathname } = useLocation()
  const [params] = useSearchParams()
  const version = deckIds ? chosenVersion(params.get('version'), deckIds) : params.get('version')
  const switcher = deckIds == null || deckIds.length > 1 ? <div className="h-[44px]" /> : null
  const tail = pathname.split('/').filter(Boolean)
  const after = tail.slice(tail.indexOf('decks') + 2)
  if (after[0] === undefined) {
    return (
      <div className="space-y-8">
        {switcher}
        <DeckOverviewFrames versionCount={version == null ? (deckIds?.length ?? UNKNOWN_VERSIONS) : 0} />
      </div>
    )
  }
  if (after[0] === 'matchups' && after.length === 1) {
    return (
      <div className="space-y-8">
        {switcher}
        <MatchupsFrames />
      </div>
    )
  }
  if (after[0] === 'matchups') {
    return (
      <PairingOutline
        deckKey={deckKey ?? id ?? ''}
        version={version}
        switcher={switcher}
        brief={ai && deckKey != null && <ai.PairingBrief deckKey={deckKey} opponentKey={opponent} />}
      />
    )
  }
  if (after[0] === 'guide' && after.length === 1) {
    return <GuidePending deckKey={deckKey ?? undefined} />
  }
  return <OutlineCard words={t('decks.reading')} height="h-64" />
}

/** What the layout hands the pages under it. `deckKey` is the deck's key.
 *  `versionIds` are the versions a page reads: every one of the deck's, or
 *  the one `?version=` chose, which is `version` (`null` for every
 *  version). `deckId` is the version `/api/decks` says was played last. */
export type DeckOutletContext = {
  deckKey: string
  deckId: string
  versionIds: string[]
  version: string | null
}

/** The layout a deck's four pages share: the way back to every deck, the
 *  deck's name as typed (muted "Unnamed deck" without one), the field's name
 *  for it when the guide gives one that differs, the deck's line (its
 *  format and when it was last played), the deck strip over the versions
 *  the tab reads (`DeckKeyNumbers`; on the Guide and RCQ, which drop `?version=`,
 *  every version), and the navigation between Overview, Matchups, Guide
 *  and RCQ.
 *
 *  `:id` is a deck's key, its colon written bare (`lib/decks.ts`'s
 *  `deckAddress`). An address that names one of a deck's versions instead,
 *  as addresses did before, or spells the key's colon `%3A`, is sent on to
 *  the deck's own, the page under it, the query and the hash kept, in
 *  place of the history entry. An id that names no deck says so and
 *  renders none of the four.
 *
 *  `?version=` names one of the deck's versions to read alone; absent, or
 *  a value that is not one of the deck's versions, or on a deck of one
 *  version, it is every version. The Overview and Matchups tabs carry a
 *  chosen version to each other; the Guide and RCQ tabs leave it behind. */
export function DeckLayout() {
  const { t } = useTranslation()
  const { id } = useParams()
  const location = useLocation()
  const identities = useGuideDecks()
  const versions = useDecks()
  const now = useNow()
  const [params] = useSearchParams()

  const resolved = identities.data ? resolveDeck(id, identities.data) : null
  const deckIds = resolved?.identity.deck_ids
  const version = deckIds ? chosenVersion(params.get('version'), deckIds) : params.get('version')
  // Kept from one render to the next (the clock re-renders the layout every
  // second), so a page that memoizes on it does not start over each time.
  const versionIds = useMemo(() => (version ? [version] : (deckIds ?? [])), [version, deckIds])
  // The field's name, from the guide; while it loads, or when it fails, the
  // line is simply absent (the Guide page shows the guide's own error).
  const guide = useGuide(resolved?.identity.key)

  const pending = identities.isPending || versions.isPending
  if (!pending && identities.error) return <ErrorNote error={identities.error} />
  if (!pending && versions.error) return <ErrorNote error={versions.error} />

  const deckId = resolved && versions.data ? newestVersion(resolved.identity, versions.data) : null
  if (!pending && (!resolved || !deckId)) {
    return (
      <EmptyState
        title={t('decks.layout.notFound.title')}
        message={t('decks.layout.notFound.message')}
        action={<Button href="/decks">{t('decks.layout.allDecks')}</Button>}
      />
    )
  }
  // A version's id, or the key with its colon as `%3A`: on to the deck's
  // own address, which redirects no further.
  const redirect = !pending && resolved ? deckRedirect(location.pathname, resolved.identity.key) : null
  if (redirect != null) {
    return <Navigate replace to={`${redirect}${location.search}${location.hash}`} />
  }

  // Pending or loaded, one tree: the same root, the same header with its
  // back link, name, line, strip and tabs in the same slots, so the tabs
  // keep their place and focus when the data arrives.
  const identity = pending ? null : (resolved?.identity ?? null)
  const fieldName = identity && guide.data ? fieldNameLine(guide.data.list_diff?.archetype_name, identity.name, t) : null
  const context: DeckOutletContext | null =
    identity && deckId ? { deckKey: identity.key, deckId, versionIds, version } : null
  const versionSearch = version ? `?${new URLSearchParams({ version })}` : ''
  const line = identity ? deckLine(identity, now, t) : null

  return (
    <div className={`${pending ? '' : 'arrive '}space-y-6`}>
      <div className="space-y-2">
        <p className="text-caption">
          <BackLink href="/decks">{t('decks.layout.allDecks')}</BackLink>
        </p>
        <div>
          {identity ? (
            <h2 className={`font-display text-title break-words ${identity.name ? 'text-ink' : 'text-muted'}`}>
              {identity.name ?? t('common.unnamedDeck')}
            </h2>
          ) : (
            <Skeleton className="h-[calc(var(--text-title)*1.25)] w-1/3" />
          )}
          {fieldName && <p className="text-body text-ink2">{fieldName}</p>}
        </div>
        {identity ? (
          line && <p className="text-caption text-muted">{line}</p>
        ) : (
          <Skeleton className="h-[calc(var(--text-caption)*1.4)] w-1/4" />
        )}
        {identity ? <DeckKeyNumbers versionIds={versionIds} /> : <StripFrames />}
        <DeckTabs versionSearch={versionSearch} />
      </div>
      {context ? (
        <Outlet context={context} />
      ) : (
        <BodyFrames deckKey={resolved?.identity.key ?? null} deckIds={identities.data ? resolved?.identity.deck_ids : undefined} />
      )}
    </div>
  )
}
