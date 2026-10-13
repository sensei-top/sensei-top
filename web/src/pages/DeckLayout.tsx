import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, NavLink, Outlet, useLocation, useParams, useSearchParams } from 'react-router'
import { useDecks, useGuide, useGuideDecks } from '../api'
import type { TFunction } from '../i18n'
import { BackLink, Button, EmptyState, ErrorNote, Loading } from '../components/ui'
import { chosenVersion } from '../lib/deckOverview'
import { deckLine, deckRedirect, fieldNameLine, newestVersion, resolveDeck } from '../lib/decks'
import { useNow } from '../lib/time'

/** The deck's tabs. Overview and Matchups read the version the address
 *  chose, so their links keep it; the Guide reads the deck whole, and
 *  its link drops it. */
function deckTabs(t: TFunction) {
  return [
    { to: '.', label: t('decks.layout.tabs.overview'), end: true, keepsVersion: true },
    { to: 'matchups', label: t('decks.layout.tabs.matchups'), end: false, keepsVersion: true },
    { to: 'guide', label: t('decks.layout.tabs.guide'), end: false, keepsVersion: false },
  ]
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

/** The layout a deck's three pages share: the way back to every deck, the
 *  deck's name as typed (muted "Unnamed deck" without one), the field's name
 *  for it when the guide gives one that differs, the deck's line over the
 *  whole deck (every version, whichever the address chose), and the
 *  navigation between Overview, Matchups and Guide.
 *
 *  `:id` is a deck's key, its colon written bare (`lib/decks.ts`'s
 *  `deckAddress`). An address that names one of a deck's versions instead,
 *  as addresses did before, or spells the key's colon `%3A`, is sent on to
 *  the deck's own, the page under it, the query and the hash kept, in
 *  place of the history entry. An id that names no deck says so and
 *  renders none of the three.
 *
 *  `?version=` names one of the deck's versions to read alone; absent, or
 *  a value that is not one of the deck's versions, or on a deck of one
 *  version, it is every version. The Overview and Matchups tabs carry a
 *  chosen version to each other; the Guide's tab leaves it behind. */
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
  const version = deckIds ? chosenVersion(params.get('version'), deckIds) : null
  // Kept from one render to the next (the clock re-renders the layout every
  // second), so a page that memoizes on it does not start over each time.
  const versionIds = useMemo(() => (version ? [version] : (deckIds ?? [])), [version, deckIds])
  // The field's name, from the guide; while it loads, or when it fails, the
  // line is simply absent (the Guide page shows the guide's own error).
  const guide = useGuide(resolved?.identity.key)

  if (identities.isPending || versions.isPending) return <Loading />
  if (identities.error) return <ErrorNote error={identities.error} />
  if (versions.error) return <ErrorNote error={versions.error} />

  const deckId = resolved ? newestVersion(resolved.identity, versions.data) : null
  if (!resolved || !deckId) {
    return (
      <EmptyState
        title={t('decks.layout.notFound.title')}
        message={t('decks.layout.notFound.message')}
        action={<Button href="/decks">{t('decks.layout.allDecks')}</Button>}
      />
    )
  }
  const { identity } = resolved
  // A version's id, or the key with its colon as `%3A`: on to the deck's
  // own address, which redirects no further.
  const redirect = deckRedirect(location.pathname, identity.key)
  if (redirect != null) {
    return <Navigate replace to={`${redirect}${location.search}${location.hash}`} />
  }

  const fieldName = guide.data ? fieldNameLine(guide.data.list_diff?.archetype_name, identity.name, t) : null
  const context: DeckOutletContext = { deckKey: identity.key, deckId, versionIds, version }
  const versionSearch = version ? `?${new URLSearchParams({ version })}` : ''

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <p className="text-caption">
          <BackLink href="/decks">{t('decks.layout.allDecks')}</BackLink>
        </p>
        <div>
          <h2 className={`font-display text-title break-words ${identity.name ? 'text-ink' : 'text-muted'}`}>
            {identity.name ?? t('common.unnamedDeck')}
          </h2>
          {fieldName && <p className="text-body text-ink2">{fieldName}</p>}
        </div>
        <p className="text-caption text-muted">{deckLine(identity, now, t)}</p>
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
      </div>
      <Outlet context={context} />
    </div>
  )
}
