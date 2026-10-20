import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { AppChange, AppSettings, Saved } from '../../bridge'
import { failureOf, settle, updateSentence } from '../../lib/settings'
import { useNow } from '../../lib/time'
import { Button, Card } from '../ui'
import { PressButton, SavingSwitch } from './SaveButton'

/** The shell's own preferences in one card: its version, whether it starts
 *  with the system (where the copy can start at login), keeps running with
 *  the window closed (Linux only), checks for updates and writes a detailed
 *  log, then the buttons for the logs and the diagnostics zip. The server
 *  never reads any of it, so a change goes through `set`, never the config.
 *  Only a shell has any of it, so with no shell the page does not draw this
 *  section. Its last row links to the welcome steps. With no functions to
 *  call, every value is text and there is nothing to press. */
export function AppSection({
  app,
  set,
  checkForUpdates,
  restartToUpdate,
  showLogs,
  exportDiagnostics,
}: {
  app: AppSettings
  set?: (change: AppChange) => Promise<Saved>
  checkForUpdates?: () => Promise<Saved>
  restartToUpdate?: () => Promise<Saved>
  showLogs?: () => Promise<Saved>
  exportDiagnostics?: () => Promise<Saved>
}) {
  const { t } = useTranslation()
  // A failed press is shown until the update state next changes: a check the
  // button did not start (the tray, the daily timer) moves the state on and
  // retires it. While the state is `failed`, the status sentence already says
  // so.
  const [updateFailure, setUpdateFailure] = useState<string | null>(null)
  const [restartFailure, setRestartFailure] = useState<string | null>(null)
  const [seenState, setSeenState] = useState(app.update.state)
  if (seenState !== app.update.state) {
    setSeenState(app.update.state)
    setUpdateFailure(null)
    setRestartFailure(null)
  }
  const now = useNow()
  const sentence = updateSentence(app.update, now, t)
  const [failure, setFailure] = useState<string | null>(null)
  const press =
    (action: () => Promise<Saved>, say: (sentence: string | null) => void) => async (): Promise<boolean> => {
      say(null)
      const sentence = failureOf(await settle(action(), t), t)
      say(sentence)
      return sentence === null
    }
  return (
    <Card title={t('settings.sections.app')} subtitle={t('settings.app.subtitle')} className="max-w-3xl">
      <div className="space-y-5">
        <p className="text-body text-ink2">{t('settings.app.version', { version: app.version })}</p>
        {app.canAutostart && (
          <SavingSwitch
            label={app.platform === 'win32' ? t('settings.app.startWindows') : t('settings.app.startLogin')}
            description={t('settings.app.startDescription')}
            checked={app.startWithSystem}
            onSave={set && ((on) => set({ startWithSystem: on }))}
          />
        )}
        {app.platform === 'linux' && (
          <SavingSwitch
            label={t('settings.app.keepRunning')}
            description={t('settings.app.keepRunningDescription')}
            checked={app.keepRunningOnClose}
            onSave={set && ((on) => set({ keepRunningOnClose: on }))}
          />
        )}
        <div className="space-y-2">
          {app.update.state === 'unavailable' ? (
            <p className="text-body text-ink2">{sentence}</p>
          ) : (
            <>
              <SavingSwitch
                label={t('settings.app.checkForUpdates')}
                description={t('settings.app.checkForUpdatesDescription')}
                checked={app.checkForUpdates}
                onSave={
                  set &&
                  ((on) => {
                    setUpdateFailure(null)
                    return set({ checkForUpdates: on })
                  })
                }
              />
              {checkForUpdates && app.checkForUpdates && (
                <PressButton
                  variant="quiet"
                  label={t('settings.app.checkNow')}
                  workingLabel={t('settings.app.checking')}
                  doneLabel={null}
                  onPress={press(checkForUpdates, setUpdateFailure)}
                />
              )}
              {checkForUpdates && app.checkForUpdates && app.update.state !== 'failed' &&
                updateFailure && (
                <p className="break-words text-caption text-loss">{updateFailure}</p>
              )}
              {sentence && <p className="text-caption text-muted">{sentence}</p>}
              {app.update.state === 'ready' && restartToUpdate && (
                <PressButton
                  variant="quiet"
                  label={t('settings.app.restartToUpdate')}
                  workingLabel={t('settings.app.restarting')}
                  doneLabel={null}
                  onPress={press(restartToUpdate, setRestartFailure)}
                />
              )}
              {app.update.state === 'ready' && restartToUpdate && restartFailure && (
                <p className="break-words text-caption text-loss">{restartFailure}</p>
              )}
            </>
          )}
        </div>
        <SavingSwitch
          label={t('settings.app.diagnostic')}
          description={t('settings.app.diagnosticDescription')}
          checked={app.diagnostic}
          onSave={set && ((on) => set({ diagnostic: on }))}
        />
        {(showLogs || exportDiagnostics) && (
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              {showLogs && (
                <PressButton
                  variant="quiet"
                  label={t('settings.app.showLogs')}
                  workingLabel={t('common.opening')}
                  doneLabel={null}
                  onPress={press(showLogs, setFailure)}
                />
              )}
              {exportDiagnostics && (
                <PressButton
                  variant="quiet"
                  label={t('settings.app.exportDiagnostics')}
                  workingLabel={t('settings.app.exporting')}
                  doneLabel={null}
                  onPress={press(exportDiagnostics, setFailure)}
                />
              )}
            </div>
            {failure && <p className="break-words text-caption text-loss">{failure}</p>}
            <p className="text-caption text-muted">{t('settings.app.exportNote')}</p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-body text-ink2">{t('settings.app.welcomeSteps')}</p>
          <Button variant="quiet" className="min-h-[44px]" href="/welcome">
            {t('settings.app.welcomeAgain')}
          </Button>
        </div>
      </div>
    </Card>
  )
}
