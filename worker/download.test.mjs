// node --test worker/download.test.mjs (run by tests/test_site.py)
import assert from 'node:assert/strict'
import { afterEach, test } from 'node:test'

import { fileUrl, RELEASES } from './download.mjs'
import worker from './index.mjs'

// The two feeds v0.7.0 published, as GitHub served them.
const WINDOWS_FEED = `version: 0.7.0
files:
  - url: Sensei-Top-Setup-0.7.0.exe
    sha512: SKofg7K/4WN8laLzdT3y36W5Wv/75cZuRGecWxFulOSwcJesHIIgOfLUIQ26tmMtMCi+dlW1Xb2tnrCBaLcsjw==
    size: 128319035
path: Sensei-Top-Setup-0.7.0.exe
sha512: SKofg7K/4WN8laLzdT3y36W5Wv/75cZuRGecWxFulOSwcJesHIIgOfLUIQ26tmMtMCi+dlW1Xb2tnrCBaLcsjw==
releaseDate: '2026-10-13T00:54:36.667Z'
`
const LINUX_FEED = `version: 0.7.0
files:
  - url: Sensei-Top-0.7.0.AppImage
    sha512: mWz4KBACX0IijMdYOOPe7kgwaxSWcBRI1CLwH+v7A3jg+h2mn09sCcnPhJoBELl4AEnX2b0sm6lFFYph9EQYXg==
    size: 158771376
    blockMapSize: 166084
path: Sensei-Top-0.7.0.AppImage
sha512: mWz4KBACX0IijMdYOOPe7kgwaxSWcBRI1CLwH+v7A3jg+h2mn09sCcnPhJoBELl4AEnX2b0sm6lFFYph9EQYXg==
releaseDate: '2026-10-13T00:52:35.564Z'
`

const realFetch = globalThis.fetch
afterEach(() => {
  globalThis.fetch = realFetch
})

const ASSETS = { fetch: async () => new Response('asset', { status: 200 }) }

function serve(feeds) {
  const asked = []
  globalThis.fetch = async (url) => {
    asked.push(url)
    if (!(url in feeds)) return new Response('Not Found', { status: 404 })
    if (feeds[url] instanceof Error) throw feeds[url]
    return new Response(feeds[url], { status: 200 })
  }
  return asked
}

const get = (path) => worker.fetch(new Request(`https://senseitop.com${path}`), { ASSETS })

test('each feed names its own file in its own release', () => {
  assert.equal(fileUrl(WINDOWS_FEED, '.exe'), `${RELEASES}/download/v0.7.0/Sensei-Top-Setup-0.7.0.exe`)
  assert.equal(fileUrl(LINUX_FEED, '.AppImage'), `${RELEASES}/download/v0.7.0/Sensei-Top-0.7.0.AppImage`)
})

test('a feed that is not what electron-builder writes names nothing', () => {
  assert.equal(fileUrl('', '.exe'), null)
  assert.equal(fileUrl('<!DOCTYPE html><html>', '.exe'), null)
  assert.equal(fileUrl(WINDOWS_FEED, '.AppImage'), null)
  assert.equal(fileUrl(WINDOWS_FEED.replace('path: Sensei', 'path: ../Sensei'), '.exe'), null)
  assert.equal(fileUrl(WINDOWS_FEED.replace('version: 0.7.0', 'version: latest'), '.exe'), null)
})

test('/download/windows and /download/linux redirect to the newest file', async () => {
  const asked = serve({
    [`${RELEASES}/latest/download/latest.yml`]: WINDOWS_FEED,
    [`${RELEASES}/latest/download/latest-linux.yml`]: LINUX_FEED,
  })
  const windows = await get('/download/windows')
  assert.equal(windows.status, 302)
  assert.equal(windows.headers.get('Location'), `${RELEASES}/download/v0.7.0/Sensei-Top-Setup-0.7.0.exe`)
  assert.equal(windows.headers.get('Cache-Control'), 'no-store')
  const linux = await get('/download/linux')
  assert.equal(linux.headers.get('Location'), `${RELEASES}/download/v0.7.0/Sensei-Top-0.7.0.AppImage`)
  assert.deepEqual(asked, [`${RELEASES}/latest/download/latest.yml`, `${RELEASES}/latest/download/latest-linux.yml`])
})

test('without a usable feed the redirect goes to the releases page', async () => {
  serve({})
  assert.equal((await get('/download/windows')).headers.get('Location'), `${RELEASES}/latest`)
  serve({ [`${RELEASES}/latest/download/latest.yml`]: new TypeError('network') })
  assert.equal((await get('/download/windows')).headers.get('Location'), `${RELEASES}/latest`)
  serve({ [`${RELEASES}/latest/download/latest.yml`]: '<!DOCTYPE html>' })
  assert.equal((await get('/download/windows')).headers.get('Location'), `${RELEASES}/latest`)
})

test('any other path is the static assets', async () => {
  const asked = serve({})
  for (const path of ['/download/', '/download/mac', '/download/constructor', '/download/windows/', '/']) {
    assert.equal(await (await get(path)).text(), 'asset', path)
  }
  assert.deepEqual(asked, [])
})
