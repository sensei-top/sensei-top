// node --test worker/language.test.mjs (run by tests/test_site.py)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import worker from './index.mjs'

const ASSETS = { fetch: async () => new Response('asset', { status: 200 }) }

// Node's Request has no `cf`; the Workers runtime fills it in from the edge.
function get(path, { country, referer } = {}) {
  const request = new Request(`https://senseitop.com${path}`, {
    headers: referer ? { Referer: referer } : {},
  })
  if (country) Object.defineProperty(request, 'cf', { value: { country } })
  return worker.fetch(request, { ASSETS })
}

test('a visitor in Brazil arriving from elsewhere gets the Portuguese page', async () => {
  for (const [path, portuguese] of [
    ['/', '/pt-br/'],
    ['/help/', '/pt-br/help/'],
    ['/privacy/', '/pt-br/privacy/'],
    ['/?utm_source=x', '/pt-br/?utm_source=x'],
  ]) {
    for (const referer of [undefined, 'https://www.google.com/', 'not a url']) {
      const response = await get(path, { country: 'BR', referer })
      assert.equal(response.status, 302, `${path} from ${referer}`)
      assert.equal(response.headers.get('Location'), portuguese)
      assert.equal(response.headers.get('Cache-Control'), 'no-store')
    }
  }
})

test('a visitor in Brazil moving around the site keeps the English page', async () => {
  for (const referer of ['https://senseitop.com/pt-br/', 'https://senseitop.com/']) {
    assert.equal(await (await get('/', { country: 'BR', referer })).text(), 'asset', referer)
  }
})

test('anyone else, and any Portuguese page, is served as asked', async () => {
  for (const country of [undefined, 'PT', 'US', 'XX', 'T1']) {
    assert.equal(await (await get('/', { country })).text(), 'asset', country)
  }
  for (const path of ['/pt-br/', '/pt-br/help/', '/pt-br/privacy/', '/site.css', '/404.html', '/privacy']) {
    assert.equal(await (await get(path, { country: 'BR' })).text(), 'asset', path)
  }
})
