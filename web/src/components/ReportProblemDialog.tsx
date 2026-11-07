import { useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMatchDetail } from '../api'
import { useShell, type ReportOutcome, type ShellReports } from '../bridge'
import {
  aboutOf,
  blockerOf,
  COUNTER_FROM,
  outcomeKey,
  REPORT_LIMIT,
  detailOf,
  type ReportKind,
  sendControls,
  standingConsentOf,
  wasSent,
} from '../lib/reportProblem'
import { useNow } from '../lib/time'
import { Button, Dialog, MoreAbout, Segmented } from './ui'

/** The line naming the match a report from its page is about. Shown, never
 *  sent: only the match's ID goes. Nothing while the match loads or if it fails. */
function AboutMatch({ matchId }: { matchId: string }) {
  const { t } = useTranslation()
  const now = useNow()
  const match = useMatchDetail(matchId).data
  const about = match ? aboutOf(match, now) : null
  return about ? <p className="break-words text-caption text-muted">{t(about.key, about.values)}</p> : null
}

/** The Report a problem dialog. The shell mounts it with a new `key` for each
 *  opening, so every opening starts with an empty draft and both boxes
 *  unticked; `signedIn`, `message` and the standing consent (a line in place of the
 *  box) are read once, then, so neither flips while a report is on its way. `message` is an error's, shown
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
  page = null,
  matchId = null,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  send: ShellReports['reportProblem']
  signedIn: boolean
  message: string | null
  /** Where it was opened: the address path and a match's ID, read once like `signedIn`. */
  page?: string | null
  matchId?: string | null
}) {
  const { t, i18n } = useTranslation()
  const [signedInThen] = useState(signedIn)
  const [detail] = useState(() => detailOf(message))
  const [kind, setKind] = useState<ReportKind>('bug')
  const idea = kind === 'idea'
  const [text, setText] = useState('')
  const [attachLog, setAttachLog] = useState(false)
  const [ticked, setTicked] = useState(false)
  const account = useShell()?.app?.settings.account
  const [standing] = useState(() => standingConsentOf(account))
  const agreed = standing || ticked
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
    draft: () => ({
      text,
      attachLog,
      agreed,
      detail: detail && t('common.technicalDetail', { message: detail }),
      kind,
      page,
      matchId,
    }),
    dismissed,
    setBusy,
    setOutcome,
    reopen: () => onOpenChange(true),
  })

  const sent = outcome !== null && wasSent(outcome)
  const hint =
    blocker === 'noText'
      ? t(idea ? 'report.dialog.hint.noTextIdea' : 'report.dialog.hint.noText')
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
      title={t(idea ? 'report.dialog.titleIdea' : 'report.dialog.title')}
      actions={
        sent ? (
          <Button variant="primary" className="min-h-[44px]" onClick={close}>
            {t('report.dialog.close')}
          </Button>
        ) : (
          <>
            <Button variant="primary" className="min-h-[44px]" disabled={busy || blocker !== null} onClick={submit}>
              {busy ? t('report.dialog.sending') : t(idea ? 'report.dialog.sendIdea' : 'report.dialog.send')}
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
            {t(outcomeKey(outcome, kind))}
          </p>
        ) : hint && !busy ? (
          <p className="text-caption text-muted">{hint}</p>
        ) : null
      }
    >
      {sent ? (
        <p>{t(outcomeKey(outcome, kind))}</p>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <span className="text-caption font-medium text-ink2">{t('report.dialog.kind.label')}</span>
            <Segmented
              value={kind}
              onChange={setKind}
              size="sm"
              label={t('report.dialog.kind.label')}
              options={[
                { value: 'bug', label: t('report.dialog.kind.bug') },
                { value: 'idea', label: t('report.dialog.kind.idea') },
              ]}
            />
          </div>

          {matchId && <AboutMatch matchId={matchId} />}

          <div className="flex flex-col gap-1.5">
            <label htmlFor={textId} className="text-caption font-medium text-ink2">
              {t(idea ? 'report.dialog.text.ideaLabel' : 'report.dialog.text.label')}
            </label>
            <textarea
              id={textId}
              value={text}
              rows={5}
              disabled={busy}
              onChange={(event) => setText(event.target.value)}
              placeholder={t(idea ? 'report.dialog.text.ideaPlaceholder' : 'report.dialog.text.placeholder')}
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

          {detail && !idea && (
            <div className="space-y-1">
              <p className="text-caption text-muted">{t('report.dialog.detail')}</p>
              <p className="break-words text-caption text-ink2">{detail}</p>
            </div>
          )}

          {!idea && (
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
            </div>
          )}

          <MoreAbout>
            <p>{t('report.dialog.intro')}</p>
            <p>{t('report.dialog.holds')}</p>
            <p>{signedInThen ? t('report.dialog.signedIn') : t('report.dialog.signedOut')}</p>
            <p>{t('report.dialog.kept')}</p>
            {!idea && <p>{t('report.dialog.log.scrubbed')}</p>}
            {!idea && <p>{t('report.dialog.log.remains')}</p>}
            <p>{t('report.dialog.transfer.where')}</p>
            <p>{t('report.dialog.transfer.ip')}</p>
            <p>{standing ? t('report.dialog.consent.withdraw') : t('report.dialog.transfer.decline')}</p>
          </MoreAbout>

          {standing ? (
            <p className="text-caption text-muted">{t('report.dialog.consent.standing')}</p>
          ) : (
            <label className="flex items-start gap-3 text-body text-ink">
              <input
                type="checkbox"
                className="mt-1 size-4 shrink-0 accent-accent"
                checked={ticked}
                disabled={busy}
                onChange={(event) => setTicked(event.target.checked)}
              />
              <span>{t('report.dialog.transfer.agree')}</span>
            </label>
          )}
        </div>
      )}
    </Dialog>
  )
}
