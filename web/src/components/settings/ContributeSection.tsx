import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Shell } from '../../bridge'
import { ContributeAge } from '../ContributeQuestion'
import {
  answerFor,
  dialogNeeded,
  settingsFailureKey,
  stateKey,
  submitAnswer,
  turnOffAnswer,
  turnOnAnswer,
} from '../../lib/contribute'
import { formatDate } from '../../lib/format'
import { POLICY_VERSION } from '../../lib/policy'
import { Button, Card, Dialog, Switch } from '../ui'
import { WithSaved } from './SaveButton'
import { useSavedFlash } from './useSavedFlash'

const BODY = ['what', 'where', 'final', 'stop'] as const

/** The first-yes dialog. Remounted per opening (`key`), so the age box
 *  starts unticked each time. Cancel takes the focus the checkbox would
 *  otherwise get. */
function ContributeDialog({
  open,
  busy,
  failure,
  onCancel,
  onConfirm,
}: {
  open: boolean
  busy: boolean
  failure: string | null
  onCancel: () => void
  onConfirm: (age: boolean) => void
}) {
  const { t } = useTranslation()
  const [age, setAge] = useState(false)
  const cancel = useRef<HTMLButtonElement>(null)
  // After the Dialog's own effect has opened it (a child's effect runs first).
  useEffect(() => {
    if (open) cancel.current?.focus()
  }, [open])
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={t('contribute.settings.dialog.title')}
      actions={
        <>
          <Button ref={cancel} variant="primary" className="min-h-[44px]" disabled={busy} onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button className="min-h-[44px]" disabled={busy || !age} onClick={() => onConfirm(age)}>
            {busy ? t('account.dialog.working') : t('contribute.answer.yes')}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="space-y-1">
          {BODY.map((line) => (
            <p key={line}>{t(`contribute.disclosure.${line}`)}</p>
          ))}
        </div>
        <ContributeAge checked={age} disabled={busy} onChange={setAge} />
        {!age && <p className="text-caption text-muted">{t('contribute.settings.dialog.hint')}</p>}
        {failure && (
          <p role="alert" className="break-words text-caption text-loss">
            {failure}
          </p>
        )}
      </div>
    </Dialog>
  )
}

/** The "Help build the stats" card. Absent where the shell cannot save the
 *  answer or the build cannot upload. */
export function ContributeSection({ shell }: { shell: Shell }) {
  const { t } = useTranslation()
  const settings = shell.app?.settings
  const [open, setOpen] = useState(false)
  const [opening, setOpening] = useState(0)
  const [busy, setBusy] = useState(false)
  const [visit, setVisit] = useState<'on' | 'off' | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [dialogFailure, setDialogFailure] = useState<string | null>(null)
  const saved = useSavedFlash()
  if (!settings?.canContribute || !shell.contribSet) return null

  const stored = settings.contribute
  const save = shell.contribSet
  const yes = stored?.yes === true

  const run = async (turnedOn: boolean, answer: Parameters<typeof save>[0], inDialog: boolean) => {
    setBusy(true)
    setFailure(null)
    setDialogFailure(null)
    saved.clear()
    const ok = await submitAnswer(answer, save, t)
    setBusy(false)
    if (ok) {
      saved.flash()
      setOpen(false)
      setVisit(inDialog ? null : turnedOn ? 'on' : 'off')
      return
    }
    const line = t(`contribute.settings.failure.${settingsFailureKey(turnedOn)}`)
    setVisit(null)
    // A dialog dismissed while the call ran comes back to say it failed.
    if (inDialog) {
      setDialogFailure(line)
      setOpen(true)
    } else setFailure(line)
  }

  const change = (next: boolean) => {
    if (!next) return void run(false, turnOffAnswer(stored, POLICY_VERSION), false)
    if (dialogNeeded(stored, POLICY_VERSION)) {
      setOpening((n) => n + 1)
      setDialogFailure(null)
      setFailure(null)
      setOpen(true)
      return
    }
    void run(true, turnOnAnswer(POLICY_VERSION), false)
  }

  const confirm = (age: boolean) => {
    const answer = answerFor(true, age, stored, POLICY_VERSION)
    if (answer) void run(true, answer, true)
  }

  const key = stateKey(stored, visit)
  const date = stored ? formatDate(new Date(stored.answeredAt), { dateStyle: 'long' }) : ''
  return (
    <Card>
      <div className="space-y-1.5">
        <WithSaved shown={saved.shown}>
          <Switch
            label={t('contribute.heading')}
            description={t('contribute.settings.description')}
            checked={yes}
            onChange={change}
            disabled={busy}
          />
        </WithSaved>
        <p className="text-caption text-ink2">{t(`contribute.settings.state.${key}`, { date })}</p>
        {failure && (
          <p role="alert" className="break-words text-caption text-loss">
            {failure}
          </p>
        )}
        {opening > 0 && (
          <ContributeDialog
            key={opening}
            open={open}
            busy={busy}
            failure={dialogFailure}
            onCancel={() => setOpen(false)}
            onConfirm={confirm}
          />
        )}
      </div>
    </Card>
  )
}
