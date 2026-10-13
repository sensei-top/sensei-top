// Captures every dashboard view at each width, so a change to the look can be
// compared against what was there before. Run against a server that is
// already up:
//
//     pnpm shots --label before
//     pnpm shots --label phase-3 --widths 1280,360 --base http://127.0.0.1:5173
//     pnpm shots --label pt-br --locale pt-BR
//
// No `--` before the flags: pnpm forwards it as written, and parseArgs then
// refuses it as a positional.
//
// Two rules this script does not bend:
//
// - It only ever sends GET. Every other method is aborted before it leaves the
//   page, so no capture can press its way into a metered call or a write route
//   (AGENTS.md non-negotiables #5 and #6), whatever it ends up clicking.
// - Its output holds real match history — opponents' handles, decklists — so
//   the default directory is under `.claude/handoffs/`, which is gitignored.
//   Point `--out` somewhere tracked and that is on you.

import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { parseArgs } from 'node:util'
import { chromium } from 'playwright'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

// Every view by its address, in the rail's order (web/src/shell/places.ts),
// each place followed by the pages under it. `:match` is the newest match
// and `:deck` the key of the first deck `/api/guide/decks` answers (the last
// played); `:largest` is the key of the deck with the most matches, and
// `:version` that deck's version `/api/decks` says was played last, so its
// Overview is captured over every version and over one, and its Matchups
// over every version. `:event` is the key of the first event
// `/api/metagame/events` answers, asked with no parameters, so the route's
// own defaults: the default format, the last 90 days, every tier, newest
// first. All are asked for below; a view that needs one the database does
// not have is skipped and said so.
const VIEWS = [
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
  { id: 'field', path: '/field' },
  { id: 'field-event', path: '/field/events/:event' },
  { id: 'coach', path: '/coach' },
  { id: 'settings', path: '/settings' },
  // Outside the shell, in place of the app.
  { id: 'design', path: '/design' },
  { id: 'not-found', path: '/no-such-page' },
]

const { values: args } = parseArgs({
  options: {
    base: { type: 'string', default: 'http://127.0.0.1:8000' },
    label: { type: 'string', default: 'current' },
    out: { type: 'string' },
    widths: { type: 'string', default: '1280,360' },
    height: { type: 'string', default: '900' },
    only: { type: 'string' },
    // The browser's own language (`pt-BR`), which a page with no stored
    // choice follows as "System"; the dashboard is captured in it.
    locale: { type: 'string', default: 'en-US' },
  },
})

const widths = args.widths.split(',').map((w) => Number.parseInt(w, 10))
const height = Number.parseInt(args.height, 10)
const outRoot = args.out ?? path.join(REPO_ROOT, '.claude', 'handoffs', 'redesign', 'screens', args.label)
const wanted = args.only ? new Set(args.only.split(',')) : null
const views = wanted ? VIEWS.filter((v) => wanted.has(v.id)) : VIEWS

/** Every row a list route answers, by GET like everything else here, or
 *  an empty list when it cannot be read. `/api/matches` is newest first,
 *  `/api/guide/decks` last played first. */
async function rowsOf(route) {
  try {
    const response = await fetch(new URL(route, args.base))
    if (!response.ok) return []
    const rows = await response.json()
    return Array.isArray(rows) ? rows : []
  } catch {
    return []
  }
}

const matches = await rowsOf('/api/matches?source=all')
const identities = await rowsOf('/api/guide/decks')
const versions = await rowsOf('/api/decks')
const events = await rowsOf('/api/metagame/events')

/** The deck with the most matches, the first answered when two tie. */
const largest = identities.reduce((most, identity) => (most == null || identity.matches > most.matches ? identity : most), null)

/** Of `identity`'s versions, the one `/api/decks` says was played last. */
function newestVersionOf(identity) {
  if (identity == null) return null
  const played = versions
    .filter((row) => identity.deck_ids.includes(row.deck_id))
    .sort((a, b) => String(b.last_played ?? '').localeCompare(String(a.last_played ?? '')))
  return played[0]?.deck_id ?? identity.deck_ids[0] ?? null
}

const ids = {
  match: matches[0]?.match_id ?? null,
  deck: identities[0]?.key ?? null,
  largest: largest?.key ?? null,
  version: newestVersionOf(largest),
  event: events[0]?.key ?? null,
}

/** The view's address with its placeholders filled in, or null when the
 *  database has none to fill one with. */
function addressOf(view) {
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
async function settle(page) {
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

const MAX_HEIGHT = 16_000

/** Recharts draws a chart in over 1.5 s by default (a pie starts 0.4 s
 *  late), and starts over whenever its container changes size. The capture
 *  waits this long after the viewport's last change, with a margin. */
const DRAW_IN_MS = 2_000

/** The window scrolls, and `fullPage` would capture it by resizing the
 *  viewport to the document, which restarts every chart's draw-in and
 *  catches its first frame, with no bars. So the viewport grows to the
 *  document's height first, and `fullPage` then has nothing to resize.
 *  Returns whether the document is taller than `MAX_HEIGHT`: `fullPage`
 *  still resizes for such a page, and its charts may be empty. */
async function growToDocument(page, width) {
  const documentHeight = await page.evaluate(() => document.documentElement.scrollHeight)
  const viewport = page.viewportSize()
  if (documentHeight > viewport.height) {
    await page.setViewportSize({ width, height: Math.min(documentHeight, MAX_HEIGHT) })
  }
  return documentHeight > MAX_HEIGHT
}

/** Live from 48rem up is capped at the viewport and scroll
 *  inside its own panes, where `fullPage` stops at the viewport. Grow the
 *  viewport by whatever the tallest scroller is hiding. Runs after
 *  `growToDocument` and before the draw-in wait, so its own resize is one
 *  the wait covers. */
async function growToContent(page, width) {
  const hidden = await page.evaluate(() => {
    let most = 0
    for (const el of document.querySelectorAll('*')) {
      if (!/(auto|scroll)/.test(getComputedStyle(el).overflowY)) continue
      most = Math.max(most, el.scrollHeight - el.clientHeight)
    }
    return most
  })
  if (hidden > 0) {
    const current = page.viewportSize().height
    await page.setViewportSize({ width, height: Math.min(current + hidden, MAX_HEIGHT) })
  }
}

const browser = await chromium.launch()
const failures = []
try {
  for (const width of widths) {
    const context = await browser.newContext({
      viewport: { width, height },
      deviceScaleFactor: 1,
      colorScheme: 'dark',
      locale: args.locale,
    })
    const page = await context.newPage()
    await page.route('**/*', (route) =>
      route.request().method() === 'GET' ? route.continue() : route.abort('blockedbyclient'),
    )
    const dir = path.join(outRoot, String(width))
    await mkdir(dir, { recursive: true })

    for (const view of views) {
      try {
        const address = addressOf(view)
        if (address === null) {
          console.log(`${width}  ${view.id}  (skipped: the database has no ${view.path.includes(':match') ? 'match' : view.path.includes(':event') ? 'event' : 'deck'})`)
          continue
        }
        // Every view from a cold load of its own address, the way a link or
        // a reload opens it.
        await page.goto(new URL(address, args.base).href, { waitUntil: 'domcontentloaded' })
        const loaded = await settle(page)
        const tooTall = await growToDocument(page, width)
        await growToContent(page, width)
        // The viewport is done changing: now the charts can finish drawing.
        await page.waitForTimeout(DRAW_IN_MS)
        await page.screenshot({ path: path.join(dir, `${view.id}.png`), fullPage: true })
        await page.setViewportSize({ width, height })
        const notes = [
          loaded ? null : 'still loading when captured',
          tooTall ? `taller than ${MAX_HEIGHT} px, so its charts may be empty` : null,
        ].filter(Boolean)
        console.log(`${width}  ${view.id}${notes.map((note) => `  (${note})`).join('')}`)
      } catch (error) {
        failures.push(`${width} ${view.id}: ${String(error).split('\n')[0]}`)
      }
    }
    await context.close()
  }
} finally {
  await browser.close()
}

console.log(`\nwritten to ${path.relative(REPO_ROOT, outRoot)}`)
if (failures.length > 0) {
  console.error(`\n${failures.length} view(s) not captured:`)
  for (const failure of failures) console.error(`  ${failure}`)
  process.exitCode = 1
}
