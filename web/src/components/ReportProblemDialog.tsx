import { useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ReportOutcome, ShellReports } from '../bridge'
import {
  blockerOf,
  COUNTER_FROM,
  outcomeKey,
  REPORT_LIMIT,
  detailOf,
  sendControls,
  wasSent,
} from '../lib/reportProblem'
import { Button, Dialog } from './ui'

/** The Report a problem dialog. The shell mounts it with a new `key` for each
 *  opening, so every opening starts with an empty draft and both boxes
 *  unticked; `signedIn` and `message` are read once, then, so the intro does
 *  not flip while a report is on its way. `message` is an error's, shown
 *  apart from the field as a technical detail and sent under it. A dialog dismissed mid-send comes
 *  back (`onOpenChange(true)`) when the send failed, to say so. Unlike the
 *  other dialogs, the primary is Send report, not the safe answer: the
 *  person opened it to send one, and Cancel keeps the focus. The outcome and
 *  the hint sit in the footer, beside the buttons they are about. */
export function ReportProblemDialog({
  open,
  onOpenChange,
  send,
  signedIn,
  message,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  send: ShellReports['reportProblem']
  signedIn: boolean
  message: string | null
}) {
  const { t, i18n } = useTranslation()
  const [signedInThen] = useState(signedIn)
  const [detail] = useState(() => detailOf(message))
  const [text, setText] = useState('')
  const [attachLog, setAttachLog] = useState(false)
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<ReportOutcome | null>(null)
  const dismissed = useRef(false)
  const textId = useId()
  const noteId = `${textId}-note`

  const blocker = blockerOf({ text, agreed })
  const tooLong = text.length > REPORT_LIMIT
  const close = () => onOpenChange(false)

  const { send: submit } = sendControls({
    call: send,
    draft: () => ({ text, attachLog, agreed, detail: detail && t('common.technicalDetail', { message: detail }) }),
    dismissed,
    setBusy,
    setOutcome,
    reopen: () => onOpenChange(true),
  })

  const sent = outcome !== null && wasSent(outcome)
  const hint =
    blocker === 'noText'
      ? t('report.dialog.hint.noText')
      : blocker === 'notAgreed'
        ? t('report.dialog.hint.notAgreed')
        : null

  return (
    <Dialog
      open={open}
      onClose={() => {
        dismissed.current = busy
        close()
      }}
      title={t('report.dialog.title')}
      actions={
        sent ? (
          <Button variant="primary" className="min-h-[44px]" onClick={close}>
            {t('report.dialog.close')}
          </Button>
        ) : (
          <>
            <Button variant="primary" className="min-h-[44px]" disabled={busy || blocker !== null} onClick={submit}>
              {busy ? t('report.dialog.sending') : t('report.dialog.send')}
            </Button>
            <Button className="min-h-[44px]" autoFocus disabled={busy} onClick={close}>
              {t('report.dialog.cancel')}
            </Button>
          </>
        )
      }
      status={
        sent ? null : outcome !== null ? (
          <p role="alert" className="break-words text-caption text-loss">
            {t(outcomeKey(outcome))}
          </p>
        ) : hint && !busy ? (
          <p className="text-caption text-muted">{hint}</p>
        ) : null
      }
    >
      {sent ? (
        <p>{t(outcomeKey(outcome))}</p>
      ) : (
        <div className="space-y-4">
          <div className="space-y-2">
            <p>{t('report.dialog.intro')}</p>
            <p>{t('report.dialog.holds')}</p>
            <p>{signedInThen ? t('report.dialog.signedIn') : t('report.dialog.signedOut')}</p>
            <p>{t('report.dialog.kept')}</p>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor={textId} className="text-caption font-medium text-ink2">
              {t('report.dialog.text.label')}
            </label>
            <textarea
              id={textId}
              value={text}
              rows={5}
              disabled={busy}
              onChange={(event) => setText(event.target.value)}
              placeholder={t('report.dialog.text.placeholder')}
              spellCheck
              aria-invalid={tooLong ? true : undefined}
              aria-describedby={tooLong || text.length >= COUNTER_FROM ? noteId : undefined}
              className={`w-full resize-y rounded-control border bg-surface px-3 py-2 text-body text-ink placeholder:text-muted disabled:opacity-50 ${
                tooLong ? 'border-loss' : 'border-edge'
              }`}
            />
            {text.length >= COUNTER_FROM && (
              <p id={noteId} className={`text-caption ${tooLong ? 'text-loss' : 'text-muted'}`}>
                {tooLong
                  ? t('report.dialog.text.tooLong')
                  : t('report.dialog.text.counter', { chars: text.length.toLocaleString(i18n.language) })}
              </p>
            )}
          </div>

          {detail && (
            <div className="space-y-1">
              <p className="text-caption text-muted">{t('report.dialog.detail')}</p>
              <p className="break-words text-caption text-ink2">{detail}</p>
            </div>
          )}

          <div className="space-y-1">
            <label className="flex items-start gap-3 text-body text-ink">
              <input
                type="checkbox"
                className="mt-1 size-4 shrink-0 accent-accent"
                checked={attachLog}
                disabled={busy}
                onChange={(event) => setAttachLog(event.target.checked)}
              />
              <span>{t('report.dialog.log.label')}</span>
            </label>
            <p className="pl-7 text-caption text-muted">{t('report.dialog.log.scrubbed')}</p>
            <p className="pl-7 text-caption text-muted">{t('report.dialog.log.remains')}</p>
          </div>

          <div className="space-y-2 rounded-block bg-surface2 p-3">
            <h3 className="text-body font-medium text-ink">{t('report.dialog.transfer.title')}</h3>
            <p className="text-caption text-muted">{t('report.dialog.transfer.where')}</p>
            <p className="text-caption text-muted">{t('report.dialog.transfer.ip')}</p>
            <label className="flex items-start gap-3 text-body text-ink">
              <input
                type="checkbox"
                className="mt-1 size-4 shrink-0 accent-accent"
                checked={agreed}
                disabled={busy}
                onChange={(event) => setAgreed(event.target.checked)}
              />
              <span>{t('report.dialog.transfer.agree')}</span>
            </label>
            <p className="text-caption text-muted">{t('report.dialog.transfer.decline')}</p>
          </div>
        </div>
      )}
    </Dialog>
  )
}
