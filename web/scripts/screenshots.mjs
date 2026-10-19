// Captures every dashboard view at each width, so a change to the look can be
// compared against what was there before. Run against a server that is
// already up:
//
//     pnpm shots --label before
//     pnpm shots --label phase-3 --widths 1280,1008 --base http://127.0.0.1:5173
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
import { DRAW_IN_MS, VIEWS, addressOf, resolveIds, settle } from './views.mjs'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')

const { values: args } = parseArgs({
  options: {
    base: { type: 'string', default: 'http://127.0.0.1:8000' },
    label: { type: 'string', default: 'current' },
    out: { type: 'string' },
    widths: { type: 'string', default: '1280,1008' },
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

const ids = await resolveIds(args.base)

const MAX_HEIGHT = 16_000

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
        const address = addressOf(view, ids)
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
