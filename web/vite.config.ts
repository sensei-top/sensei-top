import { realpathSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'
import { buildNotices, fsPackageReader } from './scripts/thirdPartyNotices.ts'

const nodeModules = fileURLToPath(new URL('./node_modules/', import.meta.url))

/** Package folders whose code is in the bundle though no module id in it
 *  names them, virtual or not. The two @fontsource-variable packages need
 *  no entry here: their CSS shows up in the chunk's modules by itself. */
function unseenPackages(): string[] {
  return [
    // Tailwind's own CSS (its preflight and theme, pulled in by
    // `@import "tailwindcss"` in index.css) is inlined by @tailwindcss/vite,
    // so the CSS carries it under index.css's id, not one of Tailwind's.
    realpathSync(join(nodeModules, 'tailwindcss')),
  ]
}

/** The packages behind the bundle's virtual modules: Vite's own helpers
 *  (`\0vite/preload-helper.js`) and Rolldown's runtime
 *  (`\0rolldown/runtime.js`). Rolldown is Vite's dependency, not ours, so
 *  it is resolved from Vite's own folder: the copy Vite itself loads.
 *  Any other virtual id fails the build. */
function virtualDirs(): Record<string, string> {
  const vite = realpathSync(join(nodeModules, 'vite'))
  const rolldown = dirname(createRequire(join(vite, 'package.json')).resolve('rolldown/package.json'))
  return {
    '\0vite/': vite,
    '\0rolldown/': realpathSync(rolldown),
  }
}

/** Vite's LICENSE.md is its own MIT licence followed by the licences of
 *  every dependency Vite bundles into itself, which run in the build and
 *  never reach the page; only Vite's own section is kept. If the heading
 *  ever goes, the build fails rather than copying the whole file or none
 *  of it. */
const LICENCE_CUTS = { vite: { heading: '# Licenses of bundled dependencies' } }

/** Rolldown's LICENSE is its own MIT licence. Its runtime, which is in the
 *  bundle, derives from esbuild, whose MIT notice is in Rolldown's
 *  THIRD-PARTY-LICENSE (with Rollup's), a name the licence-file pattern
 *  does not catch; it is taken whole. */
const EXTRA_LICENCE_FILES = { rolldown: ['THIRD-PARTY-LICENSE'] }

/** Code a package took from another work whose notice it does not ship:
 *  d3-array's src/quickselect.js is based on quickselect (ISC), and
 *  react-dom's client build includes code from Modernizr (MIT). Each text
 *  is kept in a file of its own, in scripts/notices/, so it stays byte for
 *  byte. */
const notice = (file: string) => fileURLToPath(new URL(`./scripts/notices/${file}`, import.meta.url))
const EXTRA_NOTICES = {
  'd3-array': [notice('d3-array-quickselect.txt')],
  'react-dom': [notice('react-dom-modernizr.txt')],
}

/** Writes `third-party-notices.txt` beside index.html: every package whose
 *  modules end up in the bundle, read from the chunks once Rollup has
 *  settled them, then the Mana glyphs (scripts/thirdPartyNotices.ts). A
 *  package with neither a licence file nor a `license` field, a named file
 *  or notice file that is missing, or a virtual module of no known package
 *  fails the build. */
function thirdPartyNotices(): Plugin {
  return {
    name: 'sensei-top:third-party-notices',
    apply: 'build',
    generateBundle(_options, bundle) {
      const ids = Object.values(bundle).flatMap((item) =>
        item.type === 'chunk' ? Object.keys(item.modules) : [],
      )
      const notices = buildNotices(ids, fsPackageReader, {
        extraDirs: unseenPackages(),
        cuts: LICENCE_CUTS,
        extraFiles: EXTRA_LICENCE_FILES,
        virtualDirs: virtualDirs(),
        extraNotices: EXTRA_NOTICES,
      })
      if (notices.errors.length > 0) {
        this.error(`third-party notices: ${notices.errors.join('; ')}`)
      }
      this.emitFile({ type: 'asset', fileName: 'third-party-notices.txt', source: notices.text })
    },
  }
}

export default defineConfig({
  plugins: [react(), tailwindcss(), thirdPartyNotices()],
  // The build lands inside the Python package so the wheel carries it;
  // emptyOutDir is explicit because the folder is outside Vite's root.
  build: {
    outDir: '../src/sensei_top/web_dist',
    emptyOutDir: true,
    // No polyfill: index.html has no modulepreload link, and Vite's preload
    // helper falls back to rel=preload where modulepreload is missing.
    modulePreload: { polyfill: false },
  },
  server: {
    // Fixed addresses, both sides: the API is always :8000 and the dev server
    // always :5173. strictPort makes Vite fail loudly instead of hopping to
    // 5174 and silently changing the URL.
    port: 5173,
    strictPort: true,
    // Proxy rather than CORS: the dashboard and the API stay same-origin in
    // development, exactly as they are in production where FastAPI serves
    // web_dist/ itself. Nothing here is reachable off the loopback interface.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
