import { useOutletContext, useParams, useSearchParams } from 'react-router'
import { DeckOverviewView } from '../views/DeckOverviewView'
import { GuideView } from '../views/GuideView'
import { MatchupsView } from '../views/MatchupsView'
import { PairingView } from '../views/PairingView'
import type { DeckOutletContext } from './DeckLayout'

// The pages under a deck's layout. The address names the deck by its key and
// may choose one of its versions (`?version=`); the layout resolves both and
// hands down the versions to read, every one of the deck's or the one
// chosen, and the version played last. The Overview and Matchups read the
// versions chosen, one request per version, and add them up; the Guide reads
// the deck whole, by its key, whichever version was chosen. The layout's
// line counts the whole deck whatever was chosen. A deck's pages take no
// filter: a deck is one deck on whichever client it was played, so every one
// of them asks with source="all".

/** `/decks/:id`: the chosen versions' record, play and draw, ranks and
 *  matches. Keyed by the deck alone, so moving to another deck starts the
 *  page afresh while a change of version keeps it, and with it the
 *  version select and its focus; the view keys its own Matches card on
 *  the version. */
export function DeckOverviewPage() {
  const { deckKey, versionIds, version } = useOutletContext<DeckOutletContext>()
  return <DeckOverviewView key={deckKey} deckKey={deckKey} versionIds={versionIds} version={version} />
}

/** `/decks/:id/matchups`: the chosen versions against each archetype they
 *  have met, one row per archetype and format whichever version met it.
 *  Keyed by the deck alone, as the Overview is, so a change of version
 *  keeps the version select and its focus. */
export function DeckMatchupsPage() {
  const { deckKey, versionIds, version } = useOutletContext<DeckOutletContext>()
  return <MatchupsView key={deckKey} deckKey={deckKey} versionIds={versionIds} version={version} />
}

/** `/decks/:id/matchups/:opponent`: the chosen versions against one
 *  opponent's deck, `:opponent` a Matchups row's `opponent_key` as
 *  `lib/pairing.ts`'s `pairingAddress` spells it, and `?format=`, when
 *  given, the one format whose matches it reads; without it, every
 *  format's. The router hands the param back decoded, a `%2F` as `/`, so
 *  it is the key as it is. Keyed by the deck, the opponent and the format
 *  together, so moving to another pairing starts the page afresh while a
 *  change of version keeps the version select and its focus; the view
 *  keys its own Matches card on the version. */
export function DeckPairingPage() {
  const { deckKey, versionIds, version } = useOutletContext<DeckOutletContext>()
  const { opponent = '' } = useParams()
  const [searchParams] = useSearchParams()
  const format = searchParams.get('format')
  return (
    <PairingView
      key={JSON.stringify([deckKey, opponent, format])}
      deckKey={deckKey}
      versionIds={versionIds}
      version={version}
      opponentKey={opponent}
      format={format}
    />
  )
}

/** `/decks/:id/guide`: the guide of the address's deck, read by the
 *  deck's key, whichever version the address chose. Keyed by that key,
 *  so moving to another deck starts the page afresh. */
export function DeckGuidePage() {
  const { deckKey } = useOutletContext<DeckOutletContext>()
  return <GuideView key={deckKey} deckKey={deckKey} />
}
