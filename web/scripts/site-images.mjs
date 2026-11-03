// The site's pictures: the dashboard's pages at the size of a desktop
// display, as WebP, and the 1200x630 card a shared link unfurls into. Run
// against a server that is already up on the demo database
// (`scripts/demo_db.py`), once per language:
//
//     pnpm site:images --base http://127.0.0.1:8010 --locale en-US --out /tmp/site-en
//     pnpm site:images --base http://127.0.0.1:8010 --locale pt-BR --out /tmp/site-pt
//     pnpm site:images --base http://127.0.0.1:8010 --locale en-US --out /tmp/site-en --only live --clock 2026-08-26T21:36:00
//
// `--clock <ISO 8601 date-time>` fixes the browser's `Date` at that moment
// for every dashboard page the script opens. It is for a capture of an old
// match cut mid-game: without it the Live header compares the match's start
// with today and reads "likely abandoned, no result arrived". A value with
// no zone offset is the machine's local time. Timers keep running, so the
// views still poll.
//
// No `--` before the flags (see screenshots.mjs). `--base` and `--out` have
// no default: the real server answers on a default port, and its pages hold
// real match history, which is not what the site shows.
//
// A view with a `focal: { y, height }` (CSS px; `heightByLocale` may override the height per locale) is also captured at a 1008 px
// wide viewport, tall enough to hold `y + height`, at 1.5x, clipped to
// `x: 104, width: 884` and never `fullPage` (a full-page capture restarts the
// chart's draw and leaves the sidebar short). It is written as
// `<name>-focal.png` and `.webp`: the landing's legible crop of that page. The
// 1440x900 `<name>` capture, and the card's use of `home.webp`, are unchanged.
//
// What it does not do: copy anything into `site/` or `docs/`. It writes
// `<out>/<name>.png` and `<out>/<name>.webp` for each view in `SITE_VIEWS`
// and `<out>/og.png`; the files are moved by hand, after looking at each.
//
// Rules this script keeps, as screenshots.mjs does:
//
// - It only ever sends GET. Every other method is aborted before it leaves
//   the page (AGENTS.md non-negotiables #5 and #6).
// - `magick` converts the PNG to WebP, quality 85, at the time the images
//   are made (plan 21, D11). When it is not installed, that is said and the
//   PNGs stay; the script does not throw through.

import { spawnSync } from 'node:child_process'
import { mkdir, readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parseArgs } from 'node:util'
import { DRAW_IN_MS, addressOf, resolveIds, settle } from './views.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))

/** The site's views, by the name the image carries, with the address they
 *  are captured at. The placeholders are `views.mjs`'s. */
export const SITE_VIEWS = [
  { name: 'home', path: '/', focal: { y: 72, height: 790 } },
  { name: 'matches', path: '/matches' },
  { name: 'match-report', path: '/matches/:match', focal: { y: 118, height: 640 } },
  { name: 'replay', path: '/matches/:match/replay' },
  { name: 'matchups', path: '/decks/:largest/matchups', focal: { y: 470, height: 506, heightByLocale: { 'pt-BR': 524 } } },
  { name: 'guide', path: '/decks/:largest/guide' },
  { name: 'field', path: '/field' },
  { name: 'coach', path: '/coach', focal: { y: 262, height: 630 } },
  { name: 'live', path: '/live' },
]

export const VIEWPORT = { width: 1440, height: 900 }

export const FOCAL_SCALE = 1.5

/** The viewport and clip a focal capture uses: 1008 px wide, tall enough to
 *  hold `y + height` (the locale's, when it has one), clipped to the main column. Pure, so the test reaches it
 *  without a browser.
 *  @param {{ y: number, height: number, heightByLocale?: Record<string, number> }} focal
 *  @param {string} locale */
export function focalCapture({ y, height, heightByLocale }, locale) {
  const h = heightByLocale?.[locale] ?? height
  return {
    viewport: { width: 1008, height: Math.ceil(y + h) },
    clip: { x: 104, y, width: 884, height: h },
  }
}

/** The card's text, by the browser language it is rendered in (`--locale`).
 *  `title` and `lead` repeat the landing's hero word for word, and change
 *  when the hero does: the card says what the page says, never a third
 *  wording. `brand` is the product's name and does not change. */
export const OG_TEXT = {
  'en-US': {
    brand: 'Sensei Top',
    title: 'Your matches, your decks, the real metagame. All on your own computer.',
    lead: 'Sensei Top reads the logs Arena and Magic Online already write and turns them into a dashboard: every match and game, turn by turn, your record with each deck and against each archetype, and what the tournament metagame looks like next to it.',
  },
  'pt-BR': {
    brand: 'Sensei Top',
    title: 'Suas partidas, seus decks, o meta de verdade. Tudo no seu próprio computador.',
    lead: 'O Sensei Top lê os logs que o Arena e o Magic Online já escrevem e os transforma em um dashboard: cada partida e cada jogo, turno a turno, seu histórico com cada deck e contra cada arquétipo, e o metajogo dos torneios ao lado.',
  },
}

/** Converts `png` to `webp` at quality 85 with ImageMagick. Returns
 *  `{ ok: true }`, or `{ ok: false, reason }` when the command is not
 *  installed or fails; it never throws. `command` is a parameter for the
 *  test only. */
export function convertToWebp(png, webp, command = 'magick') {
  const run = spawnSync(command, [png, '-quality', '85', webp], { encoding: 'utf8' })
  if (run.error) {
    const missing = run.error.code === 'ENOENT'
    return {
      ok: false,
      reason: missing ? `\`${command}\` is not installed (ImageMagick), so no WebP was written` : String(run.error.message),
    }
  }
  if (run.status !== 0) {
    return { ok: false, reason: `\`${command}\` exited ${run.status}: ${String(run.stderr).trim().split('\n')[0]}` }
  }
  return { ok: true }
}

/** The `--clock` value as a Date: `null` when the flag was not given, the
 *  moment when it parses, and a thrown Error when it does not. Pure, so the
 *  test can reach it without a browser. */
export function parseClock(value) {
  if (value === undefined) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) throw new Error(`--clock ${JSON.stringify(value)} is not an ISO 8601 date-time`)
  return date
}

/** Renders `og-card.html` in `locale`'s text to `<outDir>/og.png`. The
 *  slice of Home on the card is `<outDir>/home.webp` when this run wrote one,
 *  and the card is blank there when it did not. Returns the path. */
export async function renderOgCard(browser, locale, outDir, homeImage) {
  const text = OG_TEXT[locale]
  if (text === undefined) throw new Error(`no card text for locale ${locale}; the table has ${Object.keys(OG_TEXT).join(', ')}`)
  const context = await browser.newContext({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1, locale })
  try {
    const page = await context.newPage()
    await page.goto(pathToFileURL(path.join(HERE, 'og-card.html')).href)
    await page.evaluate(
      async ({ text, image }) => {
        for (const [slot, value] of Object.entries(text)) {
          document.querySelector(`[data-slot="${slot}"]`).textContent = value
        }
        const shot = document.getElementById('shot')
        if (image === null) shot.remove()
        else {
          shot.src = image
          await shot.decode()
        }
        await document.fonts.ready
      },
      { text, image: homeImage === null ? null : pathToFileURL(homeImage).href },
    )
    const target = path.join(outDir, 'og.png')
    await page.screenshot({ path: target })
    return target
  } finally {
    await context.close()
  }
}

async function main() {
  const { values: args } = parseArgs({
    options: {
      base: { type: 'string' },
      out: { type: 'string' },
      locale: { type: 'string', default: 'en-US' },
      // View names, and `og` for the card; every one by default.
      only: { type: 'string' },
      // The browser's clock for the dashboard pages, ISO 8601.
      clock: { type: 'string' },
    },
  })
  const usage =
    'usage: pnpm site:images --base <server url> --out <dir> [--locale en-US|pt-BR] [--only home,og] [--clock 2026-08-26T21:36:00]'
  if (!args.base || !args.out) {
    console.error(usage)
    process.exitCode = 2
    return
  }
  let clock
  try {
    clock = parseClock(args.clock)
  } catch (error) {
    console.error(`${error.message}\n${usage}`)
    process.exitCode = 2
    return
  }
  const outDir = path.resolve(args.out)
  const wanted = args.only ? new Set(args.only.split(',')) : null
  const views = wanted ? SITE_VIEWS.filter((view) => wanted.has(view.name)) : SITE_VIEWS
  const withCard = wanted === null || wanted.has('og')

  const { chromium } = await import('playwright')
  const ids = await resolveIds(args.base)
  await mkdir(outDir, { recursive: true })

  const browser = await chromium.launch()
  const failures = []
  let homeImage = null
  try {
    const context = await browser.newContext({
      viewport: VIEWPORT,
      deviceScaleFactor: 1,
      colorScheme: 'dark',
      locale: args.locale,
    })
    const page = await context.newPage()
    // Fixes `Date` only; timers run, which the views' polling needs. Set
    // before the first navigation. The OG card is a static file with no
    // dates on it, so it gets no clock.
    if (clock !== null) await page.clock.setFixedTime(clock)
    await page.route('**/*', (route) =>
      route.request().method() === 'GET' ? route.continue() : route.abort('blockedbyclient'),
    )
    for (const view of views) {
      try {
        const address = addressOf(view, ids)
        if (address === null) {
          console.log(`${view.name}  (skipped: the database has no ${view.path.includes(':match') ? 'match' : 'deck'} to open it on)`)
          continue
        }
        await page.goto(new URL(address, args.base).href, { waitUntil: 'domcontentloaded' })
        const loaded = await settle(page)
        await page.evaluate(() => document.fonts.ready)
        await page.waitForTimeout(DRAW_IN_MS)
        const png = path.join(outDir, `${view.name}.png`)
        const webp = path.join(outDir, `${view.name}.webp`)
        await page.screenshot({ path: png, fullPage: false })
        const converted = convertToWebp(png, webp)
        if (converted.ok && view.name === 'home') homeImage = webp
        if (view.focal) {
          const { viewport, clip } = focalCapture(view.focal, args.locale)
          const focalContext = await browser.newContext({
            viewport,
            deviceScaleFactor: FOCAL_SCALE,
            colorScheme: 'dark',
            locale: args.locale,
          })
          try {
            const focalPage = await focalContext.newPage()
            if (clock !== null) await focalPage.clock.setFixedTime(clock)
            await focalPage.route('**/*', (route) =>
              route.request().method() === 'GET' ? route.continue() : route.abort('blockedbyclient'),
            )
            await focalPage.goto(new URL(address, args.base).href, { waitUntil: 'domcontentloaded' })
            await settle(focalPage)
            await focalPage.evaluate(() => document.fonts.ready)
            await focalPage.waitForTimeout(DRAW_IN_MS)
            const focalPng = path.join(outDir, `${view.name}-focal.png`)
            await focalPage.screenshot({ path: focalPng, fullPage: false, clip })
            convertToWebp(focalPng, path.join(outDir, `${view.name}-focal.webp`))
          } finally {
            await focalContext.close()
          }
        }
        const notes = [loaded ? null : 'still loading when captured', converted.ok ? null : converted.reason].filter(Boolean)
        console.log(`${view.name}${notes.map((note) => `  (${note})`).join('')}`)
      } catch (error) {
        failures.push(`${view.name}: ${String(error).split('\n')[0]}`)
      }
    }
    await context.close()
    if (withCard) {
      try {
        // A run that only made the card finds Home's WebP from an earlier run.
        const earlier = path.join(outDir, 'home.webp')
        const slice = homeImage ?? (await readFile(earlier).then(() => earlier, () => null))
        await renderOgCard(browser, args.locale, outDir, slice)
        console.log(`og${slice === null ? '  (no home.webp beside it, so the card has no picture)' : ''}`)
      } catch (error) {
        failures.push(`og: ${String(error).split('\n')[0]}`)
      }
    }
  } finally {
    await browser.close()
  }

  console.log(`\nwritten to ${outDir}`)
  if (failures.length > 0) {
    console.error(`\n${failures.length} image(s) not made:`)
    for (const failure of failures) console.error(`  ${failure}`)
    process.exitCode = 1
  }
}

// Importing this file (the test does) runs nothing.
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await main()
