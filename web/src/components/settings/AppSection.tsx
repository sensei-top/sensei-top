import { useState } from 'react'
import type { AppChange, AppSettings, Saved } from '../../bridge'
import { failureOf, settle, updateSentence } from '../../lib/settings'
import { useNow } from '../../lib/time'
import { Card } from '../ui'
import { PressButton, SavingSwitch } from './SaveButton'

/** The shell's own preferences in one card: its version, whether it starts
 *  with the system, keeps running with the window closed (Linux only), checks
 *  for updates and writes a detailed log, then the buttons for the logs and
 *  the diagnostics zip. The server never reads any of it, so a change goes
 *  through `set`, never the config. Only a shell has any of it, so with no
 *  shell the page does not draw this section. With no functions to call,
 *  every value is text and there is nothing to press. */
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
  const sentence = updateSentence(app.update, now)
  const [failure, setFailure] = useState<string | null>(null)
  const press =
    (action: () => Promise<Saved>, say: (sentence: string | null) => void) => async (): Promise<boolean> => {
      say(null)
      const sentence = failureOf(await settle(action()))
      say(sentence)
      return sentence === null
    }
  return (
    <Card title="App" subtitle="How the app starts, closes and stays up to date." className="max-w-3xl">
      <div className="space-y-5">
        <p className="text-body text-ink2">Version {app.version}</p>
        <SavingSwitch
          label={app.platform === 'win32' ? 'Start when Windows starts' : 'Start when you log in'}
          description="Matches are recorded from the moment the computer is on, before you open Arena or Magic Online."
          checked={app.startWithSystem}
          onSave={set && ((on) => set({ startWithSystem: on }))}
        />
        {app.platform === 'linux' && (
          <SavingSwitch
            label="Keep running when the window is closed"
            description="Matches are still recorded with the window closed. Opening the app again brings the window back."
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
                label="Check for updates"
                description="At launch and once a day, the app reads one small file from the project's releases on GitHub to learn whether a new version exists, and downloads it in the background when one does. Nothing about you or your matches is sent."
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
                  label="Check now"
                  workingLabel="Checking"
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
                  label="Restart to update"
                  workingLabel="Restarting"
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
          label="Diagnostic mode"
          description="Writes much more detail to the log, for a bug report. Turning it on or off restarts the tracker for a moment."
          checked={app.diagnostic}
          onSave={set && ((on) => set({ diagnostic: on }))}
        />
        {(showLogs || exportDiagnostics) && (
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              {showLogs && (
                <PressButton
                  variant="quiet"
                  label="Show logs"
                  workingLabel="Opening"
                  doneLabel={null}
                  onPress={press(showLogs, setFailure)}
                />
              )}
              {exportDiagnostics && (
                <PressButton
                  variant="quiet"
                  label="Export diagnostics"
                  workingLabel="Exporting"
                  doneLabel={null}
                  onPress={press(exportDiagnostics, setFailure)}
                />
              )}
            </div>
            {failure && <p className="break-words text-caption text-loss">{failure}</p>}
            <p className="text-caption text-muted">
              Export diagnostics makes a zip of the logs and the app's settings, with every key removed, to attach to
              a bug report. Your matches are never in it.
            </p>
          </div>
        )}
      </div>
    </Card>
  )
}
