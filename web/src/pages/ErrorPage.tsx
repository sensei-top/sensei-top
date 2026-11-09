import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useParams, useRouteError } from 'react-router'
import { useShell } from '../bridge'
import { ReportProblemDialog } from '../components/ReportProblemDialog'
import { Button } from '../components/ui'
import { messageOf, sentKey, useBoundaryReport } from '../lib/errorReports'
import { matchIdOf, pageOf, signedInOf } from '../lib/reportProblem'

/** What the router shows in place of a page that threw. It can render where
 *  the shell's layout is not mounted (an error in the layout itself), so it
 *  mounts its own report dialog and never reads the layout's context. It
 *  reports the error itself: a boundary's catch does not reach `window`. */
export function ErrorPage() {
  const { t } = useTranslation()
  const error = useRouteError()
  const { pathname } = useLocation()
  const params = useParams()
  const sent = useBoundaryReport(error)
  const shell = useShell()
  const reportProblem = shell?.reportProblem
  const signedIn = signedInOf(shell?.app?.settings.account)
  // Remounted per opening (`key`), so each starts with a fresh draft.
  const [dialog, setDialog] = useState({ opening: 0, open: false, signedIn: false })
  return (
    <div className="mx-auto flex w-full max-w-prose flex-col items-start gap-3 px-6 py-10">
      <h1 className="font-display text-heading text-ink">{t('report.error.title')}</h1>
      <p className="text-body text-muted">{t('report.error.body')}</p>
      <p className="text-caption text-muted" aria-live="polite">
        {t(sentKey(sent))}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => window.location.reload()}>
          {t('report.error.reload')}
        </Button>
        {reportProblem && (
          <Button
            onClick={() => setDialog((now) => ({ opening: now.opening + 1, open: true, signedIn }))}
          >
            {t('report.open')}
          </Button>
        )}
      </div>
      {reportProblem && dialog.opening > 0 && (
        <ReportProblemDialog
          key={dialog.opening}
          open={dialog.open}
          onOpenChange={(open) => setDialog((now) => ({ ...now, open }))}
          send={reportProblem}
          signedIn={dialog.signedIn}
          message={messageOf(error)}
          page={pageOf(pathname)}
          matchId={matchIdOf(params, pathname)}
        />
      )}
    </div>
  )
}
