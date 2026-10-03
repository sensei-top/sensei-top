import { lazy, Suspense } from 'react'

// Loaded lazily, so it is a chunk of its own that no other page pays for.
const SurfacesView = lazy(() => import('../views/SurfacesView'))

/** `/design/surfaces`: the second reference page, Settings drawn with a
 *  sample shell, in place of the app, with no rail and no footer. */
export function DesignSurfacesPage() {
  return (
    <Suspense fallback={null}>
      <SurfacesView />
    </Suspense>
  )
}
