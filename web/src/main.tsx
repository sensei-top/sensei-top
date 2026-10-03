import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
// Two variable fonts, weight axis only, self-hosted through fontsource
// and bundled into web/dist at build time: no runtime network fetch
// (docs/design-system.md). Each file is a subset behind a unicode-range,
// so the browser reads only the ones a page's text needs.
import '@fontsource-variable/bricolage-grotesque/wght.css'
import '@fontsource-variable/hanken-grotesk/wght.css'
import '@fontsource-variable/hanken-grotesk/wght-italic.css'
import './index.css'
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
