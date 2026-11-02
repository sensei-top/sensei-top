// Photographs the cards in cards/ to demo/segments/*.png at 1920x1080.
//
//     node scripts/demo-video/capture.ts
//
// Playwright comes from web/, so this folder needs no lockfile of its own. The end
// card's name is read from demo/end-card-name.txt, which stays out of the repository.
import { mkdirSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '../..')
const { chromium } = createRequire(resolve(root, 'web/package.json'))('playwright')
const out = resolve(root, 'demo/segments')
const name = readFileSync(resolve(root, 'demo/end-card-name.txt'), 'utf8').trim()
mkdirSync(out, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } })
const shots: [string, string][] = [
  ['title.html', 'card-title'],
  ['how-built.html', 'card-how-built'],
  ['end.html', 'card-end'],
  ...[0, 1, 2, 3, 4, 5].map((n): [string, string] => [`architecture.html?step=${n}`, `card-arch-${n}`]),
]
for (const [file, shot] of shots) {
  await page.goto(`file://${resolve(root, 'scripts/demo-video/cards', file.split('?')[0])}${file.includes('?') ? `?${file.split('?')[1]}` : ''}`)
  await page.locator('.who').evaluateAll((nodes: Element[], text: string) => {
    for (const node of nodes) node.textContent = text
  }, name)
  await page.evaluate(() => document.fonts.ready)
  await page.screenshot({ path: resolve(out, `${shot}.png`) })
}
// The link preview's size, its own layout rather than the title card shrunk.
await page.setViewportSize({ width: 1200, height: 627 })
await page.goto(`file://${resolve(root, 'scripts/demo-video/cards/cover.html')}`)
await page.evaluate(() => document.fonts.ready)
for (const file of ['sensei-top-cover.png', 'thumbnail.png']) {
  await page.screenshot({ path: resolve(root, 'demo', file) })
}
await browser.close()
