// Byte ranges for the demo videos. Static assets answer a Range request with
// the whole file and a 200, which Safari refuses for video and which makes
// the chapter strip's seeking start over. Pure beyond Web standard classes.

// "bytes=a-b", "bytes=a-" or "bytes=-n" -> {start, end} (end inclusive,
// clamped), 'unsatisfiable', or null when the header is to be ignored.
function parse(header, size) {
  const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim())
  if (!match || (match[1] === '' && match[2] === '')) return null
  if (match[1] === '') {
    const n = Number(match[2])
    if (n === 0 || size === 0) return 'unsatisfiable'
    return { start: Math.max(size - n, 0), end: size - 1 }
  }
  const start = Number(match[1])
  if (start >= size) return 'unsatisfiable'
  const end = match[2] === '' ? size - 1 : Math.min(Number(match[2]), size - 1)
  return end < start ? null : { start, end }
}

export async function range(request, response) {
  if (response.status !== 200) return response
  const headers = new Headers(response.headers)
  headers.set('Accept-Ranges', 'bytes')
  const whole = () => new Response(response.body, { status: 200, headers })

  // RFC 9110: Range is ignored on any method but GET (a HEAD's asset body is empty).
  if (request.method !== 'GET') return whole()
  const wanted = request.headers.get('Range')
  if (wanted === null) return whole()
  const ifRange = request.headers.get('If-Range')
  if (ifRange !== null && ifRange !== response.headers.get('ETag')) return whole()

  const bytes = new Uint8Array(await response.arrayBuffer())
  const size = bytes.length
  const parsed = parse(wanted, size)
  if (parsed === null) return new Response(bytes, { status: 200, headers })
  if (parsed === 'unsatisfiable') {
    headers.set('Content-Range', `bytes */${size}`)
    headers.set('Content-Length', '0')
    return new Response(null, { status: 416, headers })
  }
  const { start, end } = parsed
  headers.set('Content-Range', `bytes ${start}-${end}/${size}`)
  headers.set('Content-Length', String(end - start + 1))
  return new Response(bytes.slice(start, end + 1), { status: 206, headers })
}
