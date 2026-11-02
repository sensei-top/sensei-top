// Records the product shots at 1920x1080, to demo/segments/<id>.mkv, or to
// demo/segments/pt-br/<id>.mkv with --lang pt-br.
//
//     node scripts/demo-video/record.ts [--lang en|pt-br] [--only home,live]
//
// Starts its own two servers on the copies seed.py wrote, and refuses to go on
// if a port is taken or the API names a real opponent. Every non-GET request is
// aborted before it leaves the page.
//
// A viewport of 1440x810 at a scale of 4/3 gives the site's 1440 px layout with
// crisp 1080p text, and leaves the page's own CSS alone. Frames come from CDP's
// screencast, not recordVideo, which softens small text at this size; it starts
// after the page has loaded, so there is no load to trim.
import { spawn, spawnSync } from 'node:child_process'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'
import { parseArgs } from 'node:util'

const root = resolve(import.meta.dirname, '../..')
const { chromium } = createRequire(resolve(root, 'web/package.json'))('playwright')
const { settle, resolveIds } = await import(resolve(root, 'web/scripts/views.mjs'))
const { values: args } = parseArgs({
  options: { only: { type: 'string' }, lang: { type: 'string', default: 'en' } },
})
const wanted = args.only ? new Set(args.only.split(',')) : null

// The browser's locale is the language: a context with nothing stored follows
// it, and the dashboard sends it to the API as Accept-Language.
const LANGUAGES: Record<string, { locale: string; catalogue: string; segments: string }> = {
  en: { locale: 'en-US', catalogue: 'en', segments: 'demo/segments' },
  'pt-br': { locale: 'pt-BR', catalogue: 'pt-BR', segments: 'demo/segments/pt-br' },
}
const language = LANGUAGES[args.lang as string]
if (!language) throw new Error(`no language ${args.lang}: ${Object.keys(LANGUAGES).join(', ')}`)

const data = resolve(homedir(), '.local/share/sensei-top-demo')
const segments = resolve(root, language.segments)
mkdirSync(segments, { recursive: true })
const manifest = JSON.parse(readFileSync(resolve(data, 'manifest.json'), 'utf8'))
const seconds: Record<string, number> = Object.fromEntries(
  JSON.parse(readFileSync(resolve(root, 'scripts/demo-video/shots.json'), 'utf8')).map((s: any) => [s.id, s.seconds]),
)
const UNCUT = 'http://127.0.0.1:8791'
const LIVE = 'http://127.0.0.1:8792'
// Two hours after the last match, so Home's "last session" reads naturally and
// the real date of recording never shows. The browser runs in UTC so that the
// API's naive timestamps read as written.
const UNCUT_CLOCK = new Date(`${manifest.uncut_last_match}Z`).getTime() + 2 * 3600_000
const LIVE_CLOCK = new Date(`${manifest.live_clock}Z`).getTime()

/** A dashboard string by its key, namespace first, as this language's page
 *  shows it. Every one is read before a server starts, so a key that left the
 *  catalogue stops the run there. */
function label(key: string, values: Record<string, number> = {}): string {
  const [namespace, ...path] = key.split('.')
  const file = resolve(root, 'web/src/locales', language.catalogue, `${namespace}.json`)
  const text = path.reduce((node: any, part) => node?.[part], JSON.parse(readFileSync(file, 'utf8')))
  if (typeof text !== 'string') throw new Error(`${language.catalogue} has no string at ${key}`)
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => String(values[name]))
}

const LABELS = {
  pattern: label('home.things.kicker.pattern'),
  // LibraryCard's "next draw" is its own key; two draws take this one.
  withinTwoDraws: label('live.library.within', { n: 2 }),
  couldBeHolding: label('live.opponentHand.couldBeHolding'),
  yourLibrary: label('live.library.title'),
  allMatches: label('matches.detail.all'),
  gameOne: label('matches.game.title', { n: 1 }),
  bestMatchup: label('matchups.tiles.best'),
  tierMtgo: label('field.tier.option.B'),
  tierPaper: label('field.tier.option.A'),
  beingPlayed: label('field.share.title'),
  events: label('field.events.title'),
}

// --- servers ---------------------------------------------------------------

const servers: any[] = []

async function up(base: string): Promise<boolean> {
  return fetch(`${base}/api/live`).then((r) => r.ok, () => false)
}

async function serve(db: string, port: number, base: string): Promise<void> {
  if (await up(base)) throw new Error(`port ${port} is already serving something; refusing to record it`)
  const log = resolve(data, 'empty-player.log')
  writeFileSync(log, '')
  const child = spawn(
    'uv',
    ['run', 'sensei-top', '--db', resolve(data, db), 'serve', '--port', String(port),
      '--watch', '--file', log, '--no-mtgo', '--locale', 'mdy',
      '--no-archetype-refresh', '--no-reference-refresh', '--no-backup', '--no-corpus-refresh'],
    {
      cwd: root,
      stdio: ['pipe', 'ignore', 'ignore'],
      env: { ...process.env, MTGO_HANDLE: 'Deshi', XDG_CONFIG_HOME: resolve(data, 'empty-config') },
    },
  )
  servers.push(child)
  for (let i = 0; i < 240; i++) {
    if (await up(base)) return
    await new Promise((done) => setTimeout(done, 500))
  }
  throw new Error(`the server on ${port} never came up`)
}

async function checkDemo(base: string): Promise<number> {
  const rows: any[] = await (await fetch(`${base}/api/matches?source=all`)).json()
  const foreign = rows.filter((r) => r.opponent_name != null && !/^Opponent \d+$/.test(r.opponent_name))
  if (rows.length === 0 || foreign.length > 0) {
    throw new Error(`${base} is not the demo database: ${foreign.length} of ${rows.length} rows have other names`)
  }
  return rows.length
}

// --- the page --------------------------------------------------------------

function cursorScript() {
  addEventListener('DOMContentLoaded', () => {
    const dot = document.createElement('div')
    dot.id = 'demo-cursor'
    dot.style.cssText =
      'position:fixed;left:0;top:0;width:20px;height:20px;margin:-10px 0 0 -10px;border-radius:50%;' +
      'background:rgba(255,255,255,.55);border:2px solid rgba(255,255,255,.95);box-shadow:0 0 0 2px rgba(0,0,0,.45);' +
      'pointer-events:none;z-index:2147483647;opacity:0;transition:opacity .2s'
    document.documentElement.append(dot)
    addEventListener('mousemove', (e) => {
      dot.style.opacity = '1'
      dot.style.transform = `translate(${e.clientX}px,${e.clientY}px)`
    }, true)
  })
}

// The shell at this viewport: where the sidebar ends and the content column runs.
const VIEW_WIDTH = 1440
const SIDEBAR_RIGHT = 88
const CONTENT_LEFT = 186
const CONTENT_RIGHT = 1332

class Shot {
  page: any
  id: string
  base: string
  x = 1000
  y = 500
  frames: { at: number; data: string }[] = []
  began = 0
  cdp: any
  origin = { x: 0, y: 0, scale: 1 }

  constructor(page: any, id: string, base: string) {
    this.page = page
    this.id = id
    this.base = base
  }

  async go(path: string): Promise<void> {
    await this.page.goto(new URL(path, this.base).href, { waitUntil: 'domcontentloaded' })
    await this.settled(path)
    const shown = await this.page.evaluate(() => document.documentElement.lang)
    if (shown !== language.catalogue) throw new Error(`${this.id}: the page is in ${shown}`)
    await this.page.evaluate(() => document.fonts.ready)
    await this.page.waitForTimeout(2200) // the charts' draw-in
  }

  /** Home's pattern takes minutes on a whole history: settle waits one at a time. */
  async settled(what: string): Promise<void> {
    for (let i = 0; i < 8; i++) if (await settle(this.page)) return
    throw new Error(`${this.id}: ${what} was still loading`)
  }

  async start(): Promise<void> {
    await this.page.mouse.move(this.x, this.y)
    await this.page.waitForTimeout(300)
    this.cdp = await this.page.context().newCDPSession(this.page)
    const first = await this.page.screenshot({ type: 'png' })
    this.began = Date.now() / 1000
    this.frames.push({ at: this.began, data: first.toString('base64') })
    this.cdp.on('Page.screencastFrame', (e: any) => {
      this.frames.push({ at: e.metadata.timestamp, data: e.data })
      this.cdp.send('Page.screencastFrameAck', { sessionId: e.sessionId }).catch(() => {})
    })
    await this.cdp.send('Page.startScreencast', { format: 'png', maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 })
  }

  elapsed(): number {
    return Date.now() / 1000 - this.began
  }

  async hold(ms: number): Promise<void> {
    await this.page.waitForTimeout(ms)
  }

  /** Waits until the shot has run for `s` seconds. */
  async holdUntil(s: number): Promise<void> {
    const left = s - this.elapsed()
    if (left > 0) await this.page.waitForTimeout(left * 1000)
  }

  async glideTo(x: number, y: number, ms = 700): Promise<void> {
    const [x0, y0] = [this.x, this.y]
    const t0 = Date.now()
    for (;;) {
      const t = Math.min((Date.now() - t0) / ms, 1)
      const ease = t * t * (3 - 2 * t)
      await this.page.mouse.move(x0 + (x - x0) * ease, y0 + (y - y0) * ease)
      if (t === 1) break
      await this.page.waitForTimeout(12)
    }
    this.x = x
    this.y = y
  }

  /** To the middle of `target`, or that far off it, so the dot can sit beside a
   *  word rather than on it. */
  async glide(target: any, ms = 700, dx = 0, dy = 0): Promise<void> {
    const box = await target.boundingBox()
    if (box === null) throw new Error(`${this.id}: glide target is not on the page`)
    await this.glideTo(box.x + box.width / 2 + dx, box.y + box.height / 2 + dy, ms)
  }

  /** Zooms the app around `target`, framed so no edge cuts through the sidebar or
   *  the content column. `top`, if given, is what the frame's top edge sits just
   *  above. The cursor is outside #root, so it glides with the page instead. */
  async zoom(target: any, scale = 1.2, top: any = null): Promise<void> {
    const box = await target.boundingBox()
    if (box === null) throw new Error(`${this.id}: zoom target is not on the page`)
    const shrink = 1 - 1 / scale
    const wanted = (box.x + box.width / 2) * shrink
    const lowest = Math.max(SIDEBAR_RIGHT, CONTENT_RIGHT - VIEW_WIDTH / scale)
    const left = Math.min(Math.max(wanted, lowest), CONTENT_LEFT)
    const x = left / shrink
    let y = box.y + box.height / 2
    if (top !== null) {
      const edge = await top.boundingBox()
      if (edge === null) throw new Error(`${this.id}: zoom's top edge is not on the page`)
      y = (edge.y - 40) / shrink
    }
    this.origin = { x, y, scale }
    await Promise.all([
      this.page.evaluate(({ x, y, scale }: any) => {
        const app = document.getElementById('root') as HTMLElement
        const rect = app.getBoundingClientRect()
        app.style.transformOrigin = `${x - rect.left}px ${y - rect.top}px`
        app.style.transition = 'transform .6s cubic-bezier(.4,0,.2,1)'
        app.style.transform = `scale(${scale})`
      }, { x, y, scale }),
      this.glideTo(x + (this.x - x) * scale, y + (this.y - y) * scale, 600),
    ])
    await this.page.waitForTimeout(50)
  }

  async unzoom(): Promise<void> {
    const { x, y, scale } = this.origin
    await Promise.all([
      this.page.evaluate(() => {
        ;(document.getElementById('root') as HTMLElement).style.transform = 'scale(1)'
      }),
      this.glideTo(x + (this.x - x) / scale, y + (this.y - y) / scale, 600),
    ])
    await this.page.waitForTimeout(50)
    await this.page.evaluate(() => {
      const app = document.getElementById('root') as HTMLElement
      app.style.transform = ''
      app.style.transition = ''
    })
  }

  async scrollBy(dy: number, ms: number): Promise<void> {
    await this.page.evaluate(({ dy, ms }: any) => new Promise<void>((done) => {
      const y0 = scrollY
      const t0 = performance.now()
      const step = (now: number) => {
        const t = Math.min((now - t0) / ms, 1)
        scrollTo(0, y0 + dy * (t * t * (3 - 2 * t)))
        if (t < 1) requestAnimationFrame(step)
        else done()
      }
      requestAnimationFrame(step)
    }), { dy, ms })
  }

  async finish(): Promise<void> {
    await this.holdUntil(seconds[this.id] + 0.5)
    await this.cdp.send('Page.stopScreencast')
    const end = Date.now() / 1000
    const dir = resolve(segments, `frames-${this.id}`)
    rmSync(dir, { recursive: true, force: true })
    mkdirSync(dir)
    const frames = this.frames.toSorted((a, b) => a.at - b.at)
    const lines: string[] = []
    frames.forEach((frame, i) => {
      const name = `${String(i).padStart(5, '0')}.png`
      writeFileSync(resolve(dir, name), Buffer.from(frame.data, 'base64'))
      const next = i + 1 < frames.length ? frames[i + 1].at : end
      lines.push(`file '${name}'`, `duration ${Math.max(next - frame.at, 0.001).toFixed(4)}`)
    })
    lines.push(`file '${String(frames.length - 1).padStart(5, '0')}.png'`)
    writeFileSync(resolve(dir, 'list.txt'), `${lines.join('\n')}\n`)
    const out = resolve(segments, `${this.id}.mkv`)
    const done = spawnSync('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
      '-i', resolve(dir, 'list.txt'), '-vf', 'fps=30,scale=1920:1080', '-c:v', 'libx264', '-crf', '12',
      '-preset', 'fast', '-pix_fmt', 'yuv420p', out], { stdio: 'inherit' })
    if (done.status !== 0) throw new Error(`${this.id}: ffmpeg failed`)
    rmSync(dir, { recursive: true, force: true })
    console.log(`${this.id}: ${(end - this.began).toFixed(1)} s, ${frames.length} frames`)
    if (end - this.began > seconds[this.id] + 1) console.warn(`  over its ${seconds[this.id]} s: the end is cut`)
  }
}

// --- the shots -------------------------------------------------------------

const ids = { largest: '', report: '' }

const SHOTS: Record<string, (s: Shot) => Promise<void>> = {
  async home(s) {
    await s.go('/')
    await s.start()
    await s.hold(1800)
    const pattern = s.page.getByText(LABELS.pattern, { exact: true }).first()
    await s.glide(pattern, 1200, 70)
    await s.hold(400)
    await s.zoom(pattern, 1.2)
    await s.holdUntil(9.6)
    await s.unzoom()
  },
  async live(s) {
    await s.go('/live')
    await s.start()
    await s.hold(1800)
    await s.glide(s.page.getByText(LABELS.withinTwoDraws, { exact: true }).first(), 1000, 0, -22)
    await s.hold(1400)
    const holding = s.page.getByText(LABELS.couldBeHolding, { exact: true }).first()
    await s.glide(holding, 1000)
    await s.zoom(holding, 1.25, s.page.getByText(LABELS.yourLibrary, { exact: true }).first())
    await s.glideTo(s.x + 170, s.y + 240, 1200)
    await s.holdUntil(10.8)
    await s.unzoom()
  },
  async report(s) {
    // The report first and back inside the app, so the click finds it loaded.
    await s.go(`/matches/${ids.report}`)
    await s.page.getByText(LABELS.allMatches, { exact: true }).first().click()
    const row = s.page.locator(`a[href*="${ids.report}"]`).first()
    await row.waitFor()
    await s.settled('/matches')
    await s.page.waitForTimeout(2200)
    await s.start()
    await s.hold(1800)
    await s.glide(row, 1000)
    await s.hold(500)
    await row.click()
    await s.settled('the report')
    await s.hold(1400)
    await s.scrollBy(420, 1200)
    const game = s.page.getByText(LABELS.gameOne, { exact: true }).first()
    await s.glide(game, 600, 60)
    await s.hold(300)
    await s.zoom(game, 1.15)
    await s.holdUntil(11)
    await s.unzoom()
  },
  async matchups(s) {
    await s.go(`/decks/${ids.largest}/matchups`)
    await s.start()
    await s.hold(1500)
    const best = s.page.getByText(LABELS.bestMatchup, { exact: true }).first()
    await s.glide(best, 800, 110)
    await s.zoom(best, 1.2)
    await s.hold(1600)
    await s.unzoom()
    await s.scrollBy(420, 3400)
    await s.holdUntil(9.8)
  },
  async field(s) {
    // Both tiers once beforehand, so the bars redraw instead of loading.
    await s.go('/field')
    const tiers = s.page.locator('select').nth(2)
    for (const tier of [LABELS.tierMtgo, LABELS.tierPaper]) {
      await tiers.selectOption({ label: tier })
      await s.settled(tier)
      await s.page.getByText(LABELS.beingPlayed, { exact: true }).first().waitFor({ timeout: 120_000 })
      await s.page.waitForTimeout(2500)
    }
    await s.start()
    await s.hold(1500)
    await s.glide(tiers, 800, 60)
    await s.zoom(tiers, 1.3)
    await s.hold(1000)
    await s.unzoom()
    await tiers.selectOption({ label: LABELS.tierMtgo })
    await s.hold(2000)
    const cards = await s.page.getByText(LABELS.events, { exact: true }).count()
    if (cards !== 1) throw new Error(`field: ${cards} events cards on the page`)
    await s.glide(s.page.getByText(LABELS.beingPlayed, { exact: true }).first(), 800, 170)
    await s.holdUntil(10.8)
  },
}

// --- the run ---------------------------------------------------------------

let failed = false
const browser = await chromium.launch()
try {
  await serve('uncut.db', 8791, UNCUT)
  await serve('live.db', 8792, LIVE)
  const before = await checkDemo(UNCUT)
  await checkDemo(LIVE)
  const resolved = await resolveIds(UNCUT)
  ids.largest = resolved.largest
  ids.report = manifest.report_match ?? resolved.match
  for (const [id, script] of Object.entries(SHOTS)) {
    if (wanted && !wanted.has(id)) continue
    const context = await browser.newContext({
      viewport: { width: 1440, height: 810 },
      deviceScaleFactor: 4 / 3,
      colorScheme: 'dark',
      locale: language.locale,
      timezoneId: 'UTC',
    })
    await context.clock.setFixedTime(new Date(id === 'live' ? LIVE_CLOCK : UNCUT_CLOCK))
    await context.addInitScript(cursorScript)
    await context.route('**/*', (route: any) =>
      route.request().method() === 'GET' ? route.continue() : route.abort('blockedbyclient'),
    )
    const page = await context.newPage()
    const shot = new Shot(page, id, id === 'live' ? LIVE : UNCUT)
    try {
      await script(shot)
      await shot.finish()
    } catch (error) {
      failed = true
      console.error(String(error).split('\n')[0])
      await page.screenshot({ path: resolve(segments, `failed-${id}.png`) }).catch(() => {})
    }
    await context.close()
  }
  // The watcher must not have rebuilt the copy under the recording.
  const after = await checkDemo(UNCUT)
  if (after !== before) throw new Error(`the uncut copy changed while recording: ${before} to ${after} matches`)
} finally {
  await browser.close()
  for (const child of servers) child.kill('SIGINT')
}
if (failed) process.exitCode = 1
