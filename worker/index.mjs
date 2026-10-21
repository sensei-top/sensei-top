// The site's one script. Everything else under site/ is a static asset; the
// Worker runs only for the paths `run_worker_first` in wrangler.json names,
// and anything there it does not answer goes back to the assets. The runtime
// takes every export of this module for an entry point, so it exports nothing
// else: the logic, and what its tests import, is in the modules beside it.
import { download } from './download.mjs'
import { language } from './language.mjs'
import { platform } from './platform.mjs'
import { suggest } from './suggest.mjs'

export default {
  async fetch(request, env) {
    const early = (await download(request)) ?? language(request)
    if (early) return early
    const { pathname } = new URL(request.url)
    if (pathname === '/' || pathname === '/pt-br/') {
      const os = platform(request)
      if (os === null) return suggest(await env.ASSETS.fetch(request), os)
      // Departs from S2: the rewritten page has no validator, so a cached copy
      // of the unknown-visitor page must not be told by a 304 that it is current.
      const headers = new Headers(request.headers)
      headers.delete('If-None-Match')
      headers.delete('If-Modified-Since')
      return suggest(await env.ASSETS.fetch(new Request(request, { headers })), os)
    }
    return env.ASSETS.fetch(request)
  },
}
