import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router'
import { useShell } from '../bridge'
import { ContributeQuestion } from '../components/ContributeQuestion'
import { Button, Card } from '../components/ui'
import { contribWaits, savedAnswer } from '../lib/contribute'
import { settle } from '../lib/settings'
import { NotFoundPage } from './NotFoundPage'

/** `/contribute`: "Help build the stats", put once to an install that has
 *  not answered. Mounting it uses the ask up (`contribAsked`), so Decide
 *  later, closing the window and Go to Home all mean it never shows again;
 *  Settings still asks. */
export function ContributePage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const shell = useShell()
  const app = shell?.app
  const [picked, setPicked] = useState<boolean | null>(null)
  const marked = useRef(false)
  const set = app?.set
  const canContribute = app?.settings.canContribute === true

  useEffect(() => {
    if (!set || !canContribute || marked.current) return
    marked.current = true
    // A failed write shows nothing: the page simply may show again at the next
    // launch, which is the safe side of "once".
    void settle(Promise.resolve().then(() => set({ contribAsked: true })), t)
  }, [set, canContribute, t])

  if (!shell || !app || !shell.contribSet) return <NotFoundPage />
  if (!canContribute) return <Navigate to="/" replace />

  const stored = app.settings.contribute
  const saved = savedAnswer(stored, picked)
  const home = () => void navigate('/', { replace: true })
  return (
    <div className="mx-auto max-w-3xl">
      <Card>
        <div className="space-y-5">
          <p className="text-body text-ink2">{t('contribute.page.lead')}</p>
          <ContributeQuestion
            stored={stored}
            picked={picked}
            waiting={contribWaits(true, stored, picked)}
            waitingHint={t('contribute.page.hintAnswer')}
            showHeading={false}
            onPicked={setPicked}
          />
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" disabled={saved === null} onClick={home}>
                {t('welcome.frame.goHome')}
              </Button>
              <Button variant="quiet" onClick={home}>
                {t('contribute.page.later')}
              </Button>
            </div>
            <p className="text-caption text-muted">{t('contribute.page.laterNote')}</p>
          </div>
        </div>
      </Card>
    </div>
  )
}
