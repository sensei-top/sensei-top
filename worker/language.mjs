// A visitor in Brazil who arrives at an English page from outside the site is
// sent to the same page in Portuguese. The country is the one Cloudflare
// derives for every request (`request.cf.country`); nothing is stored. A
// visitor who came from another page of the site is never redirected, so the
// English link on a Portuguese page keeps working: `_headers` sends
// `Referrer-Policy: same-origin`, which gives the site its own pages as the
// Referer and every other site none. Portuguese pages are never redirected.

export const PORTUGUESE = {
  '/': '/pt-br/',
  '/privacy/': '/pt-br/privacy/',
}

/** The redirect to the Portuguese page, or null to serve the page asked for. */
export function language(request) {
  const url = new URL(request.url)
  if (!Object.hasOwn(PORTUGUESE, url.pathname)) return null
  if (request.cf?.country !== 'BR') return null
  const referer = request.headers.get('Referer')
  if (referer && URL.canParse(referer) && new URL(referer).origin === url.origin) return null
  return new Response(null, {
    status: 302,
    headers: { Location: PORTUGUESE[url.pathname] + url.search, 'Cache-Control': 'no-store' },
  })
}
