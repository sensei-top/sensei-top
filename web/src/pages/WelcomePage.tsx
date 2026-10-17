import { useNavigate, useSearchParams } from 'react-router'
import { useShell } from '../bridge'
import { stepOf } from '../lib/welcome'
import { WelcomeView } from '../views/WelcomeView'
import { NotFoundPage } from './NotFoundPage'

/** `/welcome`: the first run's steps, one at a time, the step in the
 *  address (`?step=`) so the reload after a restore lands back on it. Which
 *  steps show is the shell's `plays`, read by the view from the app
 *  settings. Only a desktop shell has anything to set up, so with no shell
 *  the address is no page. The one caller of `useShell()` here. */
export function WelcomePage() {
  const shell = useShell()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const step = stepOf(params.get('step'))

  if (!shell?.app) return <NotFoundPage />
  const app = shell.app
  return (
    <WelcomeView
      step={step}
      sources={shell.settings.sources}
      app={app.settings}
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
