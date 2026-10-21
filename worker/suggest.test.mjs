// node --test worker/suggest.test.mjs
import assert from 'node:assert/strict'
import { test } from 'node:test'

import worker from './index.mjs'
import { VARY, button, note, suggest } from './suggest.mjs'

// HTMLRewriter does not exist under node --test: the handlers get a fake element.
function fake(attributes) {
  const map = new Map(Object.entries(attributes))
  return {
    getAttribute: (name) => map.get(name) ?? null,
    setAttribute: (name, value) => map.set(name, value),
    removeAttribute: (name) => map.delete(name),
    map,
  }
}

test('the matching download button becomes primary and the other does not', () => {
  for (const os of ['windows', 'linux']) {
    for (const target of ['windows', 'linux']) {
      // Whatever class the static page carried, the link for `os` is primary.
      const link = fake({ href: `/download/${target}`, class: target === 'windows' ? 'button primary' : 'button' })
      button(os).element(link)
      assert.equal(link.map.get('class'), target === os ? 'button primary' : 'button', `${os} / ${target}`)
    }
  }
})

test('mac and phone leave the buttons as they are', () => {
  for (const os of ['mac', 'phone']) {
    const windows = fake({ href: '/download/windows', class: 'button primary' })
    const linux = fake({ href: '/download/linux', class: 'button' })
    button(os).element(windows)
    button(os).element(linux)
    assert.equal(windows.map.get('class'), 'button primary', os)
    assert.equal(linux.map.get('class'), 'button', os)
  }
})

test('only the note for the visitor\'s system is shown', () => {
  for (const os of ['windows', 'linux', 'mac', 'phone']) {
    for (const value of ['mac', 'phone']) {
      const element = fake({ 'data-os': value, hidden: '' })
      note(os).element(element)
      assert.equal(element.map.has('hidden'), value !== os, `${os} / ${value}`)
    }
  }
})

test('an unknown system gets the page as it is, with the Vary a cache needs', async () => {
  const asset = new Response('page', { headers: { ETag: '"abc"' } })
  const response = suggest(asset, null)
  assert.equal(await response.text(), 'page')
  assert.equal(response.headers.get('Vary'), VARY)
  assert.equal(response.headers.get('ETag'), '"abc"')
})

// HTMLRewriter stub: records the handlers and passes the response through.
function stubRewriter(rewriters) {
  globalThis.HTMLRewriter = class {
    on(selector, handler) {
      rewriters.push([selector, handler])
      return this
    }
    transform(response) {
      return response
    }
  }
}

test('a rewritten response varies on the system and drops the asset\'s validators', async () => {
  const rewriters = []
  stubRewriter(rewriters)
  try {
    const asset = new Response('page', { headers: { ETag: '"abc"', 'Last-Modified': 'x', Vary: 'Accept-Encoding' } })
    const response = suggest(asset, 'linux')
    assert.equal(response.headers.get('Vary'), `Accept-Encoding, ${VARY}`)
    assert.equal(response.headers.has('ETag'), false)
    assert.equal(response.headers.has('Last-Modified'), false)
    assert.deepEqual(rewriters.map(([selector]) => selector), ['.actions a.button', '[data-os]'])

    const [buttons] = rewriters.map(([, handler]) => handler)
    const windows = fake({ href: '/download/windows', class: 'button primary' })
    const linux = fake({ href: '/download/linux', class: 'button' })
    buttons.element(windows)
    buttons.element(linux)
    assert.equal(linux.map.get('class'), 'button primary')
    assert.equal(windows.map.get('class'), 'button')
  } finally {
    delete globalThis.HTMLRewriter
  }
})

test('for mac the rewrite shows the mac note and keeps the phone note hidden', () => {
  const rewriters = []
  stubRewriter(rewriters)
  try {
    suggest(new Response('page'), 'mac')
    const [, notes] = rewriters.map(([, handler]) => handler)
    const mac = fake({ 'data-os': 'mac', hidden: '' })
    const phone = fake({ 'data-os': 'phone', hidden: '' })
    notes.element(mac)
    notes.element(phone)
    assert.equal(mac.map.has('hidden'), false)
    assert.equal(phone.map.has('hidden'), true)
  } finally {
    delete globalThis.HTMLRewriter
  }
})

test('a status other than 200 is not rewritten', () => {
  const rewriters = []
  stubRewriter(rewriters)
  try {
    const response = suggest(new Response(null, { status: 304, headers: { ETag: '"abc"' } }), 'linux')
    assert.equal(response.status, 304)
    assert.equal(response.headers.get('ETag'), '"abc"')
    assert.equal(rewriters.length, 0)
  } finally {
    delete globalThis.HTMLRewriter
  }
})

// The captured Linux Chromium row of platform.test.mjs: Chromium 154, Arch Linux.
const CHROMIUM_LINUX =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/154.0.0.0 Safari/537.36'

test('only the landings reach the rewrite, and the language redirect still comes first', async () => {
  // An asset store that honours If-None-Match, as the real one does.
  const ASSETS = {
    fetch: async (request) =>
      request.headers.get('If-None-Match') === '"abc"' || request.headers.get('If-Modified-Since') === 'x'
        ? new Response(null, { status: 304, headers: { ETag: '"abc"' } })
        : new Response('asset', { headers: { ETag: '"abc"', 'Last-Modified': 'x' } }),
  }
  const get = (path, headers = {}, country) => {
    const request = new Request(`https://senseitop.com${path}`, { headers })
    if (country) Object.defineProperty(request, 'cf', { value: { country } })
    return worker.fetch(request, { ASSETS })
  }
  const rewriters = []
  stubRewriter(rewriters)
  try {
    for (const path of ['/', '/pt-br/']) {
      rewriters.length = 0
      const known = await get(path, { 'User-Agent': CHROMIUM_LINUX, 'If-None-Match': '"abc"' })
      assert.equal(known.status, 200, path)
      assert.equal(known.headers.has('ETag'), false, path)
      assert.equal(known.headers.has('Last-Modified'), false, path)
      assert.equal(known.headers.get('Vary'), VARY, path)
      assert.equal(rewriters.length, 2, path)

      rewriters.length = 0
      const since = await get(path, { 'User-Agent': CHROMIUM_LINUX, 'If-Modified-Since': 'x' })
      assert.equal(since.status, 200, path)
      assert.equal(since.headers.has('Last-Modified'), false, path)
      assert.equal(rewriters.length, 2, path)

      rewriters.length = 0
      const unknownSince = await get(path, { 'If-Modified-Since': 'x' })
      assert.equal(unknownSince.status, 304, path)

      rewriters.length = 0
      const unknown = await get(path, { 'If-None-Match': '"abc"' })
      assert.equal(unknown.status, 304, path)
      assert.equal(unknown.headers.get('ETag'), '"abc"', path)
      assert.equal(unknown.headers.get('Vary'), VARY, path)
      assert.equal(rewriters.length, 0, path)
    }
    // Any other path is the asset as it is.
    const help = await get('/help/', { 'User-Agent': CHROMIUM_LINUX })
    assert.equal(help.headers.get('Vary'), null)
    assert.equal(help.headers.get('ETag'), '"abc"')
    // A visitor in Brazil on `/` is redirected before any rewrite.
    assert.equal((await get('/', {}, 'BR')).status, 302)
  } finally {
    delete globalThis.HTMLRewriter
  }
})
