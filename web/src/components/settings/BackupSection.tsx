import { useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { useShell, type AccountActions, type AccountReply, type AccountState, type DeepPartial, type Saved, type ShellSettings } from '../../bridge'
import { failureOf, settle, useRestart, useTextSave } from '../../lib/settings'
import { sizeOf } from '../../lib/size'
import { ago, formatCount, useNow } from '../../lib/time'
import { Button, Callout, Card, Dialog } from '../ui'
import { profileGate, switchChange, syncLine } from './accountLogic'
import { FolderField, PressButton, RestartNote, SaveButton, SavingSelect, SavingSwitch } from './SaveButton'

type Backup = ShellSettings['backup']

const KEEP_STEPS = [3, 7, 14, 30]

/** The counts the select offers, with the one saved among them when it is
 *  not one of the steps, so the select never shows a count that is not
 *  the saved one. */
function keepOptions(keep: number): { value: string; label: string }[] {
  const steps = KEEP_STEPS.includes(keep) ? KEEP_STEPS : [...KEEP_STEPS, keep].sort((a, b) => a - b)
  return steps.map((count) => ({ value: String(count), label: String(count) }))
}

/** The last part of a path, whichever way its separators lean. */
function fileName(path: string): string {
  return path.split(/[\\/]/).pop() || path
}

/** The daily copy of the matches, in two cards. The first: when the last
 *  one was made or that it failed, the folder and how many copies are
 *  kept, a backup made now, and a restore from a file, which asks first in
 *  a dialog whose safe button is the primary one, then says it takes
 *  effect at the next start and offers Restart now. The second is Cloud
 *  copy. Only a shell makes backups, so with no shell the page does not
 *  draw this section. With a shell and no functions to call, every value
 *  is text and there is nothing to press. */
export function BackupSection({
  backup,
  save,
  pickFolder,
  pickFile,
  backUpNow,
  restoreFrom,
  relaunch,
}: {
  backup: Backup
  save?: (change: DeepPartial<Backup>) => Promise<Saved>
  pickFolder?: () => Promise<string | null>
  pickFile?: () => Promise<string | null>
  backUpNow?: () => Promise<Saved>
  restoreFrom?: (path: string) => Promise<Saved>
  /** Restart now, offered after a restore; the shell's, from `useShell` when absent. */
  relaunch?: () => Promise<Saved>
}) {
  const { t } = useTranslation()
  const shell = useShell()
  const restartNow = relaunch ?? (shell?.app ? () => shell.app!.relaunch() : undefined)
  const { restart, watch } = useRestart()
  const text = useTextSave({ dir: backup.dir }, save && ((change) => watch(save({ dir: change.dir ?? undefined }))))
  const [failure, setFailure] = useState<string | null>(null)
  const [restored, setRestored] = useState(false)

  return (
    <div className="space-y-6">
      <Card
        title={t('settings.sections.backup')}
        subtitle={t('settings.backup.subtitle')}
        className="max-w-3xl"
      >
        <div className="space-y-5">
          <LastBackup last={backup.last} inFolder={backup.inFolder} />
          <FolderField
            label={t('settings.backup.folder')}
            value={save ? text.typed.dir : backup.dir}
            onChange={save && ((value) => text.type('dir', value))}
            onPick={pickFolder}
            hint={t('settings.backup.folderHint')}
            error={text.errorOf('dir')}
          />
          <SavingSelect
            label={t('settings.backup.keepLabel')}
            value={String(backup.keep)}
            options={keepOptions(backup.keep)}
            onSave={save && ((value) => watch(save({ keep: Number(value) })))}
            hint={t('settings.backup.keepHint')}
          />
          {/* A folder is never emptied: an empty field is nothing to save. */}
          {save && <SaveButton dirty={text.dirty && text.typed.dir.trim() !== ''} onSave={text.submit} />}
          {(backUpNow || (pickFile && restoreFrom)) && (
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                {backUpNow && <BackUpNowButton backUpNow={backUpNow} onFailure={setFailure} />}
                {pickFile && restoreFrom && (
                  <RestoreButton
                    pickFile={pickFile}
                    restoreFrom={restoreFrom}
                    onFailure={setFailure}
                    onRestored={() => setRestored(true)}
                  />
                )}
              </div>
              {failure && <p className="break-words text-caption text-loss">{failure}</p>}
              <AfterRestore restored={restored} relaunch={restartNow} onFailure={setFailure} />
            </div>
          )}
          <p className="text-caption text-muted">{t('settings.backup.offsite')}</p>
          <RestartNote show={restart && !restored} />
        </div>
      </Card>
      <CloudCopyCard account={shell?.app?.settings.account} actions={shell?.app?.account} />
    </div>
  )
}

/** What follows a restore: the note that it takes effect at the next
 *  start, and Restart now when the shell can relaunch. Nothing before a
 *  restore. A refusal's sentence goes to `onFailure`. */
export function AfterRestore({
  restored,
  relaunch,
  onFailure,
}: {
  restored: boolean
  relaunch?: () => Promise<Saved>
  onFailure: (sentence: string | null) => void
}) {
  const { t } = useTranslation()
  if (!restored) return null
  return (
    <>
      <p className="text-caption text-ink2">{t('settings.backup.restored')}</p>
      {relaunch && (
        <PressButton
          variant="primary"
          label={t('settings.backup.restartNow')}
          workingLabel={t('settings.backup.restartNow')}
          doneLabel={null}
          onPress={async () => {
            const sentence = failureOf(await settle(relaunch(), t), t)
            onFailure(sentence)
            return sentence === null
          }}
        />
      )}
    </>
  )
}

/** The second card: the cloud history switch, which is Account's profile
 *  write (`consentSync`, every other answer as it is). Signed out it is
 *  one line with a link to Settings → Account; signed in with no profile
 *  read (unanswered, unknown, loading) it is not drawn, since Account's own
 *  Try again and Answer now cover that. Drawn only in a build that has an
 *  account. */
export function CloudCopyCard({ account, actions }: { account?: AccountState; actions?: AccountActions }) {
  const { t } = useTranslation()
  const now = useNow()
  const [gate] = useState(profileGate)
  const [writing, setWriting] = useState(false)
  if (!account?.available || !actions) return null
  const read = account.signedIn && account.profile?.state === 'read' ? account.profile : null
  const saved = (reply: AccountReply): Saved =>
    reply.ok ? { ok: true } : { ok: false, error: t('account.welcome.error.failed') }
  // Signed in with no profile read: Account's own Try again covers it.
  if (account.signedIn && !read) return null
  const line = read ? syncLine(read.consentSync, account.sync) : null
  return (
    <Card title={t('settings.backup.cloudTitle')} className="max-w-3xl">
      {!read ? (
        <p className="text-body text-ink2">
          <Trans
            i18nKey="settings.backup.cloudSignedOut"
            components={{ account: <Link to="/settings/account" className="text-ink underline decoration-muted underline-offset-2 hover:decoration-ink" /> }}
          />
        </p>
      ) : (
        <div className="space-y-1.5">
          <SavingSwitch
            label={t('account.settings.backup.label')}
            description={t('account.settings.backup.description')}
            checked={read.consentSync}
            disabled={writing}
            onSave={async (on) => {
              const answer = await gate.run(async () => {
                setWriting(true)
                try {
                  return saved(await actions.setProfile(switchChange(read, 'consentSync', on)))
                } catch {
                  return saved({ ok: false, error: 'failed' })
                } finally {
                  setWriting(false)
                }
              })
              return answer ?? saved({ ok: false, error: 'failed' })
            }}
          />
          {line && (
            <p className="max-w-prose text-caption text-muted">
              {t(line.key, {
                count: line.count,
                n: line.count == null ? undefined : formatCount(line.count),
                when: line.when ? ago(account.sync?.lastSyncAt, now) : undefined,
              })}
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

/** The last backup as a sentence, or a callout when it failed. `ago`'s
 *  words say when, and `sizeOf`'s how large when the size is known; a time
 *  that cannot be read says nothing. */
function LastBackup({ last, inFolder }: { last: Backup['last']; inFolder: number }) {
  const { t } = useTranslation()
  const now = useNow()
  if (last === null) return <p className="text-body text-ink2">{t('settings.backup.none')}</p>
  const when = ago(last.at, now)
  if (last.ok) {
    if (when === null) return null
    return (
      <p className="text-body text-ink2">
        {last.bytes === null
          ? t('settings.backup.lastMade', { when })
          : t('settings.backup.lastMadeSized', { when, size: sizeOf(last.bytes) })}
      </p>
    )
  }
  return (
    <Callout tone="warn" title={t('settings.backup.failedTitle')}>
      {when !== null && (
        <p>
          {inFolder > 0
            ? t('settings.backup.triedWithOlder', { when })
            : t('settings.backup.triedNone', { when })}
        </p>
      )}
    </Callout>
  )
}

/** "Back up now": "Backing up" while the shell makes the copy, "Backed
 *  up" for two seconds after one that worked. A failure's sentence is the
 *  card's to show, under the buttons. */
function BackUpNowButton({
  backUpNow,
  onFailure,
}: {
  backUpNow: () => Promise<Saved>
  onFailure: (sentence: string | null) => void
}) {
  const { t } = useTranslation()
  const backUp = async (): Promise<boolean> => {
    onFailure(null)
    const sentence = failureOf(await settle(backUpNow(), t), t)
    onFailure(sentence)
    return sentence === null
  }
  return (
    <PressButton
      variant="secondary"
      label={t('settings.backup.backUpNow')}
      workingLabel={t('settings.backup.backingUp')}
      doneLabel={t('settings.backup.backedUp')}
      onPress={backUp}
    />
  )
}

/** "Restore from a backup file": the shell's file picker, then a dialog
 *  that names the file and says what restoring replaces. Its safe button,
 *  the primary one, keeps what is here; the other restores, and this
 *  button says "Restoring" until the shell answers. `label` is the
 *  button's words; the welcome steps say "Choose a backup file". */
export function RestoreButton({
  pickFile,
  restoreFrom,
  onFailure,
  onRestored,
  label,
}: {
  label?: string
  pickFile: () => Promise<string | null>
  restoreFrom: (path: string) => Promise<Saved>
  onFailure: (sentence: string | null) => void
  onRestored: () => void
}) {
  const { t } = useTranslation()
  const [file, setFile] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(false)

  const choose = async () => {
    onFailure(null)
    const chosen = await pickFile().catch(() => null)
    if (chosen !== null) setFile(chosen)
  }

  const restore = async (path: string) => {
    setRestoring(true)
    onFailure(null)
    const sentence = failureOf(await settle(restoreFrom(path), t), t)
    setRestoring(false)
    onFailure(sentence)
    if (sentence === null) onRestored()
  }

  return (
    <>
      <Button variant="quiet" className="min-h-[44px]" disabled={restoring} aria-haspopup="dialog" onClick={choose}>
        {restoring ? t('settings.backup.restoring') : (label ?? t('settings.backup.restore'))}
      </Button>
      <Dialog
        open={file !== null}
        onClose={() => setFile(null)}
        title={t('settings.backup.restoreTitle')}
        actions={
          <>
            <Button variant="primary" className="min-h-[44px]" onClick={() => setFile(null)}>
              {t('settings.backup.keepWhatIsHere')}
            </Button>
            <Button
              className="min-h-[44px]"
              onClick={() => {
                const path = file
                setFile(null)
                if (path !== null) void restore(path)
              }}
            >
              {t('settings.backup.restoreFromFile')}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <p className="break-words text-ink">{file === null ? '' : fileName(file)}</p>
          <p>{t('settings.backup.restoreBody')}</p>
        </div>
      </Dialog>
    </>
  )
}
