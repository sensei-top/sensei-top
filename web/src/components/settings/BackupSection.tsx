import { useState } from 'react'
import type { DeepPartial, Saved, ShellSettings } from '../../bridge'
import { failureOf, settle, useRestart, useTextSave } from '../../lib/settings'
import { sizeOf } from '../../lib/size'
import { ago, useNow } from '../../lib/time'
import { Button, Callout, Card, Dialog } from '../ui'
import { FolderField, PressButton, RestartNote, SaveButton, SavingSelect } from './SaveButton'

type Backup = ShellSettings['backup']

const KEEP_STEPS = [3, 7, 14, 30]

const RESTORED = 'Restored. This takes effect the next time the app starts.'

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

/** The daily copy of the matches, in one card: when the last one was made
 *  or that it failed, the folder and how many copies are kept, a backup
 *  made now, and a restore from a file, which asks first in a dialog whose
 *  safe button is the primary one. Only a shell makes backups, so with no
 *  shell the page does not draw this section. With a shell and no
 *  functions to call, every value is text and there is nothing to press. */
export function BackupSection({
  backup,
  save,
  pickFolder,
  pickFile,
  backUpNow,
  restoreFrom,
}: {
  backup: Backup
  save?: (change: DeepPartial<Backup>) => Promise<Saved>
  pickFolder?: () => Promise<string | null>
  pickFile?: () => Promise<string | null>
  backUpNow?: () => Promise<Saved>
  restoreFrom?: (path: string) => Promise<Saved>
}) {
  const { restart, watch } = useRestart()
  const text = useTextSave({ dir: backup.dir }, save && ((change) => watch(save({ dir: change.dir ?? undefined }))))
  const [failure, setFailure] = useState<string | null>(null)
  const [restored, setRestored] = useState(false)

  return (
    <Card
      title="Backup"
      subtitle="A copy of your matches, made once a day and checked after it is made."
      className="max-w-3xl"
    >
      <div className="space-y-5">
        <LastBackup last={backup.last} inFolder={backup.inFolder} />
        <FolderField
          label="Folder"
          value={save ? text.typed.dir : backup.dir}
          onChange={save && ((value) => text.type('dir', value))}
          onPick={pickFolder}
          hint="Where the copies are kept."
          error={text.errorOf('dir')}
        />
        <SavingSelect
          label="Copies kept"
          value={String(backup.keep)}
          options={keepOptions(backup.keep)}
          onSave={save && ((value) => watch(save({ keep: Number(value) })))}
          hint="The oldest is removed when a new one is made."
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
            {restored && <p className="text-caption text-ink2">{RESTORED}</p>}
          </div>
        )}
        <p className="text-caption text-muted">
          A folder that Dropbox or OneDrive already copies keeps a backup off this computer at no cost.
        </p>
        <RestartNote show={restart && !restored} />
      </div>
    </Card>
  )
}

/** The last backup as a sentence, or a callout when it failed. `ago`'s
 *  words say when, and `sizeOf`'s how large when the size is known; a time
 *  that cannot be read says nothing. */
function LastBackup({ last, inFolder }: { last: Backup['last']; inFolder: number }) {
  const now = useNow()
  if (last === null) return <p className="text-body text-ink2">No backup has been made.</p>
  const when = ago(last.at, now)
  if (last.ok) {
    if (when === null) return null
    return (
      <p className="text-body text-ink2">
        {last.bytes === null
          ? `The last backup was made ${when}.`
          : `The last backup was made ${when} and holds ${sizeOf(last.bytes)}.`}
      </p>
    )
  }
  return (
    <Callout tone="warn" title="The last backup failed">
      {when !== null && (
        <p>
          {inFolder > 0
            ? `It was tried ${when}. The one before it is still in the folder.`
            : `It was tried ${when}. No backup is in the folder.`}
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
  const backUp = async (): Promise<boolean> => {
    onFailure(null)
    const sentence = failureOf(await settle(backUpNow()))
    onFailure(sentence)
    return sentence === null
  }
  return (
    <PressButton
      variant="secondary"
      label="Back up now"
      workingLabel="Backing up"
      doneLabel="Backed up"
      onPress={backUp}
    />
  )
}

/** "Restore from a backup file": the shell's file picker, then a dialog
 *  that names the file and says what restoring replaces. Its safe button,
 *  the primary one, keeps what is here; the other restores, and this
 *  button says "Restoring" until the shell answers. */
function RestoreButton({
  pickFile,
  restoreFrom,
  onFailure,
  onRestored,
}: {
  pickFile: () => Promise<string | null>
  restoreFrom: (path: string) => Promise<Saved>
  onFailure: (sentence: string | null) => void
  onRestored: () => void
}) {
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
    const sentence = failureOf(await settle(restoreFrom(path)))
    setRestoring(false)
    onFailure(sentence)
    if (sentence === null) onRestored()
  }

  return (
    <>
      <Button variant="quiet" className="min-h-[44px]" disabled={restoring} aria-haspopup="dialog" onClick={choose}>
        {restoring ? 'Restoring' : 'Restore from a backup file'}
      </Button>
      <Dialog
        open={file !== null}
        onClose={() => setFile(null)}
        title="Restore from this file?"
        actions={
          <>
            <Button variant="primary" className="min-h-[44px]" onClick={() => setFile(null)}>
              Keep what is here
            </Button>
            <Button
              className="min-h-[44px]"
              onClick={() => {
                const path = file
                setFile(null)
                if (path !== null) void restore(path)
              }}
            >
              Restore from the file
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <p className="break-words text-ink">{file === null ? '' : fileName(file)}</p>
          <p>Every match in the app is replaced by what the file holds. To keep what is here now, back up first.</p>
        </div>
      </Dialog>
    </>
  )
}
