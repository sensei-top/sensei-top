import { lazy, Suspense } from 'react'

// Loaded lazily, so it is a chunk of its own that no other page pays for.
const DesignView = lazy(() => import('../views/DesignView'))

/** `/design`: the design system's reference page, in place of the app
 *  rather than inside the shell. */
export function DesignPage() {
  return (
    <Suspense fallback={null}>
      <DesignView />
    </Suspense>
  )
}
