// The site's one script. Everything else under site/ is a static asset; the
// Worker runs only for the paths `run_worker_first` in wrangler.json names,
// and anything there it does not answer goes back to the assets. The runtime
// takes every export of this module for an entry point, so it exports nothing
// else: the logic, and what its tests import, is in the modules beside it.
import { download } from './download.mjs'
import { language } from './language.mjs'

export default {
  async fetch(request, env) {
    return (await download(request)) ?? language(request) ?? env.ASSETS.fetch(request)
  },
}
