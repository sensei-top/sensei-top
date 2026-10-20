// The landing for a visitor whose system is known: the matching download
// button becomes the primary one and, for a system with no build, the note
// for it is shown. The static page is a complete page for a visitor of
// unknown system; this only moves `primary` and removes `hidden`, through
// `HTMLRewriter`, so the markup is never reordered (the stylesheet's
// `.actions .primary { order: -1 }` puts the primary button first). The
// wording is in the HTML, in both languages. Nothing is stored.

export const VARY = 'Sec-CH-UA-Platform, User-Agent'

/** Handler for `.actions a.button`: `primary` goes to the link that downloads for `os`. */
export function button(os) {
  return {
    element(element) {
      if (os === 'mac' || os === 'phone') return
      const matches = element.getAttribute('href') === `/download/${os}`
      element.setAttribute('class', matches ? 'button primary' : 'button')
    },
  }
}

/** Handler for `[data-os]`: the note for `os` is shown. */
export function note(os) {
  return {
    element(element) {
      if (element.getAttribute('data-os') === os) element.removeAttribute('hidden')
    },
  }
}

/** The response with the headers a shared cache needs; when the body changes, the asset's validators are dropped. */
function varied(response, changed) {
  const headers = new Headers(response.headers)
  const vary = headers.get('Vary')
  headers.set('Vary', vary ? `${vary}, ${VARY}` : VARY)
  if (changed) {
    headers.delete('ETag')
    headers.delete('Last-Modified')
  }
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers })
}

/** The page for the visitor's system; for a null `os`, the page as it is, with the same `Vary`. */
export function suggest(response, os) {
  // Departs from "a rewrite for every known system": only a 200 has a body to
  // rewrite, and a 304 or an error is passed on as for an unknown visitor.
  if (os === null || response.status !== 200) return varied(response, false)
  return new HTMLRewriter()
    .on('.actions a.button', button(os))
    .on('[data-os]', note(os))
    .transform(varied(response, true))
}
