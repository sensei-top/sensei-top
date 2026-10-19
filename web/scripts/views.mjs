// What `screenshots.mjs` and `site-images.mjs` share: the table of dashboard
// views by address, the resolution of an address's placeholders (`:match`,
// `:deck`, `:largest`, `:version`, `:event`) from the API of a server that is
// already up, and the waits that say a page has finished loading.
//
// Everything here reads by GET. Neither script's browser sends anything else
// (each aborts every other method), and nothing here opens a browser.

// Every view by its address, in the rail's order (web/src/shell/places.ts),
// each place followed by the pages under it. `:match` is the newest match
// and `:deck` the key of the first deck `/api/guide/decks` answers (the last
// played); `:largest` is the key of the deck with the most matches, and
// `:version` that deck's version `/api/decks` says was played last, so its
// Overview is captured over every version and over one, and its Matchups
// over every version. `:event` is the key of the first event
// `/api/metagame/events` answers, asked with no parameters, so the route's
// own defaults: the default format, the last 90 days, every tier, newest
// first. All are asked for by `resolveIds`; a view that needs one the
// database does not have is skipped and said so.
export const VIEWS = [
  { id: 'home', path: '/' },
  { id: 'live', path: '/live' },
  { id: 'matches', path: '/matches' },
  { id: 'match', path: '/matches/:match' },
  { id: 'match-replay', path: '/matches/:match/replay' },
  { id: 'decks', path: '/decks' },
  { id: 'deck', path: '/decks/:deck' },
  { id: 'deck-largest', path: '/decks/:largest' },
  { id: 'deck-largest-version', path: '/decks/:largest?version=:version' },
  { id: 'deck-largest-matchups', path: '/decks/:largest/matchups' },
  { id: 'deck-matchups', path: '/decks/:deck/matchups' },
  { id: 'deck-guide', path: '/decks/:deck/guide' },
  { id: 'deck-rcq', path: '/decks/:deck/rcq' },
  { id: 'field', path: '/field' },
  { id: 'field-event', path: '/field/events/:event' },
  { id: 'coach', path: '/coach' },
  { id: 'settings', path: '/settings' },
  // Outside the shell, in place of the app.
  { id: 'design', path: '/design' },
  { id: 'not-found', path: '/no-such-page' },
]

/** Every row a list route answers, by GET like everything else here, or
 *  an empty list when it cannot be read. `/api/matches` is newest first,
 *  `/api/guide/decks` last played first. */
export async function rowsOf(base, route) {
  try {
    const response = await fetch(new URL(route, base))
    if (!response.ok) return []
    const rows = await response.json()
    return Array.isArray(rows) ? rows : []
  } catch {
    return []
  }
}

/** The deck with the most matches, the first answered when two tie. */
export function largest(identities) {
  return identities.reduce((most, identity) => (most == null || identity.matches > most.matches ? identity : most), null)
}

/** Of `identity`'s versions (`versions` is `/api/decks`' rows), the one
 *  `/api/decks` says was played last. */
export function newestVersionOf(identity, versions) {
  if (identity == null) return null
  const played = versions
    .filter((row) => identity.deck_ids.includes(row.deck_id))
    .sort((a, b) => String(b.last_played ?? '').localeCompare(String(a.last_played ?? '')))
  return played[0]?.deck_id ?? identity.deck_ids[0] ?? null
}

/** The five ids a view's address can name, each null when the database at
 *  `base` has none to give. */
export async function resolveIds(base) {
  const matches = await rowsOf(base, '/api/matches?source=all')
  const identities = await rowsOf(base, '/api/guide/decks')
  const versions = await rowsOf(base, '/api/decks')
  const events = await rowsOf(base, '/api/metagame/events')
  const most = largest(identities)
  return {
    match: matches[0]?.match_id ?? null,
    deck: identities[0]?.key ?? null,
    largest: most?.key ?? null,
    version: newestVersionOf(most, versions),
    event: events[0]?.key ?? null,
  }
}

/** The view's address with its placeholders filled in from `ids`, or null
 *  when the database has none to fill one with. */
export function addressOf(view, ids) {
  let missing = false
  const filled = view.path.replace(/:(match|deck|largest|version|event)\b/g, (_, name) => {
    if (ids[name] == null) missing = true
    // An event's key keeps its slashes, as `eventHref` writes them.
    if (name === 'event') return String(ids.event ?? '').split('/').map(encodeURIComponent).join('/')
    const encoded = encodeURIComponent(ids[name] ?? '')
    // A deck's key keeps its colon bare, as the dashboard's own address
    // spells it (web/src/lib/decks.ts's deckAddress).
    return name === 'deck' || name === 'largest' ? encoded.replace(/%3A/g, ':') : encoded
  })
  return missing ? null : filled
}

/** Data has landed when the network is quiet and no skeleton is left; a view
 *  that keeps polling never goes quiet, so both waits give up rather than
 *  fail. The skeleton wait is the long one: the deck guide takes well over
 *  five seconds on a real database.
 *  A skeleton inside `[data-sample]` is a sample on the reference page,
 *  not a page still loading, and is never waited on.
 *  Returns whether a skeleton was still up. The charts' draw-in is not
 *  waited on here: it restarts whenever the viewport changes size, so it is
 *  waited on once the viewport has stopped changing (`DRAW_IN_MS`). */
export async function settle(page) {
  await page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => {})
  return page
    .waitForFunction(
      () =>
        [...document.querySelectorAll('.animate-pulse.rounded-block')].every(
          (skeleton) => skeleton.closest('[data-sample]') !== null,
        ),
      null,
      { timeout: 60_000 },
    )
    .then(() => true)
    .catch(() => false)
}

/** Recharts draws a chart in over 1.5 s by default (a pie starts 0.4 s
 *  late), and starts over whenever its container changes size. The capture
 *  waits this long after the viewport's last change, with a margin. */
export const DRAW_IN_MS = 2_000
