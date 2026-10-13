import { useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { useMetagameStatus } from '../api'
import { useShell } from '../bridge'
import { stepOf } from '../lib/welcome'
import { WelcomeView, type DownloadsAnswer } from '../views/WelcomeView'
import { NotFoundPage } from './NotFoundPage'

/** How often step 3 asks again how old the background downloads are. */
const REFRESH_MS = 30_000

/** `/welcome`: the five steps of the first run, one at a time, the step in
 *  the address (`?step=`) so the reload after a restore lands back on it.
 *  Only a desktop shell has anything to set up, so with no shell the
 *  address is no page. The one caller of `useShell()` here; the status of
 *  the two background downloads is asked for only on step 3, and again
 *  every 30 seconds while it is shown. */
export function WelcomePage() {
  const shell = useShell()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const step = stepOf(params.get('step'))
  const watching = step === 'cards' && !!shell?.app
  const status = useMetagameStatus(undefined, watching)
  const { refetch } = status
  useEffect(() => {
    if (!watching) return
    const timer = window.setInterval(() => void refetch(), REFRESH_MS)
    return () => window.clearInterval(timer)
  }, [watching, refetch])

  if (!shell?.app) return <NotFoundPage />
  const app = shell.app
  const downloads: DownloadsAnswer = status.data
    ? {
        archetypeHours: status.data.archetype_cache_age_hours ?? null,
        corpusHours: status.data.corpus_age_hours ?? null,
      }
    : status.isError
      ? 'failed'
      : 'loading'
  return (
    <WelcomeView
      step={step}
      sources={shell.settings.sources}
      app={app.settings}
      downloads={downloads}
      actions={{
        set: (change) => app.set(change),
        recheck: () => app.recheck(),
        firstData: () => app.firstData(),
        finishOnboarding: () => app.finishOnboarding(),
        save: (change) => shell.save({ sources: change }),
        pickFolder: () => shell.pickFolder(),
        pickFile: () => shell.pickFile(),
        restoreFrom: (path) => shell.restoreFrom(path),
      }}
      onFinished={() => void navigate('/')}
    />
  )
}
