// node --test worker/range.test.mjs (run by tests/test_site.py)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import worker from './index.mjs'
import { range } from './range.mjs'

// Ten bytes, "0123456789": the slice a-b is the text from a to b.
const BYTES = new TextEncoder().encode('0123456789')
const ETAG = '"abc"'

function asset(status = 200) {
  return new Response(status === 200 ? BYTES : null, {
    status,
    headers: { ETag: ETAG, 'Content-Type': 'video/mp4', 'X-Content-Type-Options': 'nosniff' },
  })
}

function ask(headers = {}, method = 'GET', response = asset()) {
  return range(new Request('https://senseitop.com/video/x.mp4', { method, headers }), response)
}

async function partial(headers, from, to, text) {
  const response = await ask(headers)
  assert.equal(response.status, 206)
  assert.equal(response.headers.get('Content-Range'), `bytes ${from}-${to}/10`)
  assert.equal(response.headers.get('Content-Length'), String(text.length))
  assert.equal(await response.text(), text)
  assert.equal(response.headers.get('Accept-Ranges'), 'bytes')
  assert.equal(response.headers.get('ETag'), ETAG)
  assert.equal(response.headers.get('Content-Type'), 'video/mp4')
  assert.equal(response.headers.get('X-Content-Type-Options'), 'nosniff')
}

async function whole(headers) {
  const response = await ask(headers)
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('Accept-Ranges'), 'bytes')
  assert.equal(response.headers.get('ETag'), ETAG)
  assert.equal(await response.text(), '0123456789')
}

test('a status other than 200 is returned as it is', async () => {
  const response = await ask({ Range: 'bytes=0-1' }, 'GET', asset(304))
  assert.equal(response.status, 304)
  assert.equal(response.headers.get('Accept-Ranges'), null)
  const missing = await ask({ Range: 'bytes=0-1' }, 'GET', new Response('no', { status: 404 }))
  assert.equal(missing.status, 404)
})

test('the three forms of a range give a 206 with the slice', async () => {
  await partial({ Range: 'bytes=2-4' }, 2, 4, '234')
  await partial({ Range: 'bytes=7-' }, 7, 9, '789')
  await partial({ Range: 'bytes=-3' }, 7, 9, '789')
})

test('an end past the last byte is clamped, a suffix longer than the file is the file', async () => {
  await partial({ Range: 'bytes=8-99' }, 8, 9, '89')
  await partial({ Range: 'bytes=-99' }, 0, 9, '0123456789')
})

test('no Range, a malformed one, several ranges or another unit give the whole file', async () => {
  await whole({})
  for (const value of ['bytes=', 'bytes=-', 'bytes=a-b', 'bytes=5-2', 'bytes=0-1,3-4', 'items=0-1', 'nonsense']) {
    await whole({ Range: value })
  }
})

test('a range at or past the end, or the last zero bytes, is a 416', async () => {
  for (const value of ['bytes=10-', 'bytes=10-12', 'bytes=-0']) {
    const response = await ask({ Range: value })
    assert.equal(response.status, 416, value)
    assert.equal(response.headers.get('Content-Range'), 'bytes */10')
    assert.equal(await response.text(), '')
  }
})

test('If-Range is honoured only for exactly the asset ETag', async () => {
  await partial({ Range: 'bytes=0-1', 'If-Range': ETAG }, 0, 1, '01')
  await whole({ Range: 'bytes=0-1', 'If-Range': '"other"' })
  await whole({ Range: 'bytes=0-1', 'If-Range': `W/${ETAG}` })
  await whole({ Range: 'bytes=0-1', 'If-Range': 'Mon, 02 Nov 2026 00:00:00 GMT' })
})

test('Range is ignored on a HEAD, whose asset response has no body', async () => {
  const head = new Response(null, {
    status: 200,
    headers: { ETag: ETAG, 'Content-Length': '10', 'Content-Type': 'video/mp4' },
  })
  const response = await ask({ Range: 'bytes=0-1' }, 'HEAD', head)
  assert.equal(response.status, 200)
  assert.equal(response.headers.get('Content-Length'), '10')
  assert.equal(response.headers.get('Content-Range'), null)
  assert.equal(response.headers.get('Accept-Ranges'), 'bytes')
  assert.equal(await response.text(), '')
})

test('the Worker routes /video/ through it and hands the assets the request unchanged', async () => {
  let seen
  const ASSETS = {
    fetch: async (request) => {
      seen = request
      return asset()
    },
  }
  const request = new Request('https://senseitop.com/video/demo-en.mp4', { headers: { Range: 'bytes=0-3' } })
  const response = await worker.fetch(request, { ASSETS })
  assert.equal(seen, request)
  assert.equal(response.status, 206)
  assert.equal(await response.text(), '0123')
})
