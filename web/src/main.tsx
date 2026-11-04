import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
// Two variable fonts, weight axis only, self-hosted through fontsource
// and bundled into src/sensei_top/web_dist at build time: no runtime network fetch
// (docs/design-system.md). Each file is a subset behind a unicode-range,
// so the browser reads only the ones a page's text needs.
import '@fontsource-variable/bricolage-grotesque/wght.css'
import '@fontsource-variable/hanken-grotesk/wght.css'
import '@fontsource-variable/hanken-grotesk/wght-italic.css'
import './index.css'
import { readShellGlobal } from './bridge'
// The translation layer starts before anything renders: the language is
// chosen and i18next is ready when this import returns.
import { onLanguageChange } from './i18n'
import { routes } from './routes'
import { applyStoredDensity } from './shell/density'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      // The database only changes when the reader runs, so polling hard buys
      // nothing. M4 (live mode) is where this interval starts to matter.
      staleTime: 30_000,
      refetchOnWindowFocus: true,
      retry: 1,
    },
  },
})

// What the API wrote was written in the language it was asked for
// (`Accept-Language`, api.ts), so a change of language drops every answer
// once and asks again. All but the heartbeat (`live`, api.ts), which holds
// no prose: resetting it would lose the projection revision Shell.tsx
// compares, and the next beat would invalidate everything a second time.
onLanguageChange(() => void client.resetQueries({ predicate: (q) => q.queryKey[0] !== 'live' }))

// Inside the desktop shell the page's uncaught errors go to the shell, which
// drops them unless the user said yes to error reports. A plain browser has
// no bridge and does nothing.
function forwardErrors(): void {
  const report = readShellGlobal()?.reportError
  if (!report) return
  const send = (value: unknown): void => {
    const error = value instanceof Error ? value : null
    void report({
      name: error?.name ?? 'Error',
      message: error ? error.message : typeof value === 'string' ? value : 'Non-error value rejected',
      stack: error?.stack ?? null,
    }).catch(() => {})
  }
  window.addEventListener('error', (event) => send(event.error ?? event.message))
  window.addEventListener('unhandledrejection', (event) => send(event.reason))
}
forwardErrors()

// Every place is an address (routes.tsx). The router only picks the page;
// TanStack Query above it stays the only data layer.
const router = createBrowserRouter(routes)

// Before the first render, so a compact page never paints comfortable first.
applyStoredDensity()

const root = document.getElementById('root')
if (!root) throw new Error('missing #root')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
