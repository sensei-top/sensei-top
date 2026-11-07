import { useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'
import type { AccountActions, AccountReply, AccountState, ProfileState, Saved } from '../../bridge'
import { ACCOUNT_WELCOME_PATH } from '../../lib/accountWelcome'
import { failureOf } from '../../lib/settings'
import { ago, formatCount, useNow } from '../../lib/time'
import { Button, Card, MoreAbout } from '../ui'
import { DeleteAccountDialog, DeleteHistoryDialog, ErrorsDialog } from './AccountDialogs'
import {
  deleteControls,
  errorsChange,
  errorsControls,
  exportLine,
  profileGate,
  providerName,
  switchChange,
  syncLine,
  type DeleteFailure,
} from './accountLogic'
import { PressButton, SavingSwitch } from './SaveButton'
import { SignInButtons } from './SignInButtons'

/** Settings → Account: signed out, the two sign-in buttons, both off while
 *  one waits on the browser; signed in, the three choices (or Try again when
 *  the profile could not be read), the backup's status, Export, Sign out, and
 *  under their own heading the two deletes, each behind its dialog. A delete's own publication of the new account
 *  state does not redraw the section while the call runs: what shows is the
 *  state the press found. Drawn only in the shell, in a build that has an
 *  account. */
export function AccountSection({ state, actions }: { state: AccountState; actions: AccountActions }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const now = useNow()
  const [frozen, setFrozen] = useState<AccountState | null>(null)
  const view = frozen ?? state
  const latest = useRef<ProfileState | undefined>(undefined)
  latest.current = state.available ? state.profile : undefined

  const [gate] = useState(profileGate)
  const [writing, setWriting] = useState(false)
  const [signOutFailure, setSignOutFailure] = useState<string | null>(null)
  const [exportResult, setExportResult] = useState<'saved' | 'failed' | null>(null)
  const [historyResult, setHistoryResult] = useState<number | null>(null)
  const [deletedNote, setDeletedNote] = useState(false)
  const [retryFailed, setRetryFailed] = useState(false)
  const deleteHeadingId = useId()

  const [dialog, setDialog] = useState<'history' | 'account' | 'errors' | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<DeleteFailure | null>(null)
  const [errorsFailure, setErrorsFailure] = useState<string | null>(null)

  if (!view.available) return <Card className="max-w-3xl"><p className="text-body text-ink2">{t('account.settings.unavailable')}</p></Card>

  const open = (which: 'history' | 'account' | 'errors') => {
    setFailure(null)
    setErrorsFailure(null)
    setDialog(which)
  }
  const close = () => setDialog(null)

  const deleting = (kind: 'history' | 'account') =>
    deleteControls({
      kind,
      call: async () => {
        setBusy(true)
        setFailure(null)
        setFrozen(state)
        try {
          return await (kind === 'history' ? actions.deleteCloudHistory() : actions.deleteAccount())
        } finally {
          setFrozen(null)
          setBusy(false)
        }
      },
      profileNow: () => latest.current,
      close,
      settled: (outcome) => {
        if (outcome.ok) {
          close()
          if (kind === 'history') setHistoryResult(outcome.deleted ?? null)
          else setDeletedNote(true)
        } else {
          setFailure(outcome.failure)
          // A dialog dismissed while the call ran comes back, to show why.
          setDialog(kind)
        }
      },
    })
  const history = deleting('history')
  const account = deleting('account')

  const profile = view.profile
  const read = profile?.state === 'read' ? profile : null
  const saved = (reply: AccountReply): Saved => (reply.ok ? { ok: true } : { ok: false, error: t('account.welcome.error.failed') })
  const save = async (change: Parameters<AccountActions['setProfile']>[0]): Promise<Saved> => {
    const answer = await gate.run(async () => {
      setWriting(true)
      try {
        return saved(await actions.setProfile(change))
      } catch {
        return saved({ ok: false, error: 'failed' })
      } finally {
        setWriting(false)
      }
    })
    return answer ?? saved({ ok: false, error: 'failed' })
  }
  const line = syncLine(read?.consentSync ?? false, view.sync)
  const note = !view.persistence.kept ? view.persistence.reason : null
  const provider = providerName(view.provider)

  const errors =
    read &&
    errorsControls({
      profile: read,
      save: async (change) => {
        setBusy(true)
        setErrorsFailure(null)
        try {
          return await save(change)
        } finally {
          setBusy(false)
        }
      },
      close,
      settled: (result) => {
        const sentence = failureOf(result, t)
        if (sentence) {
          setErrorsFailure(sentence)
          setDialog('errors')
        } else close()
      },
    })

  const persistenceNote = note && (
    <div className="space-y-1 text-caption text-muted">
      <p>{t(`account.settings.persistence.${note}`)}</p>
      {note === 'noKeyring' && (
        <MoreAbout>
          <p className="text-caption text-muted">{t('account.settings.persistence.keyringHint')}</p>
        </MoreAbout>
      )}
    </div>
  )

  return (
    <Card className="max-w-3xl">
      <div className="space-y-5">
        {!view.signedIn ? (
          <div className="space-y-3">
            <div className="space-y-1.5 text-body text-ink2">
              <p>{t('account.settings.signedOut')}</p>
              <p>{t('account.settings.noPassword')}</p>
            </div>
            <SignInButtons signIn={actions.signIn} onStart={() => setDeletedNote(false)}>
              {persistenceNote}
            </SignInButtons>
            {deletedNote && <p className="text-body text-ink2">{t('account.deleteAccount.done')}</p>}
          </div>
        ) : (
          <>
            <p className="text-body text-ink">
              {view.email
                ? t('account.settings.signedInAs', { email: view.email, provider: provider ?? '' })
                : t('account.settings.signedInWith', { provider: provider ?? '' })}
            </p>
            {persistenceNote}

            {profile?.state === 'none' && (
              <div className="space-y-2">
                <p className="text-body text-ink2">{t('account.settings.unanswered')}</p>
                <Button variant="primary" className="min-h-[44px]" onClick={() => void navigate(ACCOUNT_WELCOME_PATH)}>
                  {t('account.settings.answerNow')}
                </Button>
              </div>
            )}
            {(profile === undefined || profile.state === 'unknown') && (
              <div className="space-y-1.5">
                <p className="max-w-prose text-body text-ink2">{t('account.settings.unknown')}</p>
                <PressButton
                  variant="quiet"
                  label={t('account.settings.retry')}
                  workingLabel={t('account.dialog.working')}
                  doneLabel={null}
                  onPress={async () => {
                    setRetryFailed(false)
                    let reply: AccountReply | null
                    try {
                      reply = await actions.readProfileAgain()
                    } catch {
                      reply = null
                    }
                    const ok = reply?.ok === true
                    setRetryFailed(!ok)
                    return ok
                  }}
                />
                {retryFailed && (
                  <p role="alert" className="break-words text-caption text-loss">
                    {t('account.settings.retryFailed')}
                  </p>
                )}
              </div>
            )}
            {read && (
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <SavingSwitch
                    label={t('account.settings.backup.label')}
                    description={t('account.settings.backup.description')}
                    checked={read.consentSync}
                    disabled={busy || writing}
                    onSave={(on) => save(switchChange(read, 'consentSync', on))}
                  />
                  {line && (
                    <p className="max-w-prose text-caption text-muted">
                      {t(line.key, {
                        count: line.count,
                        n: line.count == null ? undefined : formatCount(line.count),
                        when: line.when ? ago(view.sync?.lastSyncAt, now) : undefined,
                      })}
                    </p>
                  )}
                </div>
                <SavingSwitch
                  label={t('account.settings.errors.label')}
                  description={t('account.settings.errors.description')}
                  checked={read.consentErrors}
                  disabled={busy || writing}
                  onSave={async (on) => {
                    if (on) {
                      open('errors')
                      return { ok: true }
                    }
                    const change = errorsChange(read, false, false)
                    return change ? save(change) : { ok: false, error: t('account.welcome.error.failed') }
                  }}
                />
                <SavingSwitch
                  label={t('account.settings.coach.label')}
                  description={t('account.settings.coach.description')}
                  checked={read.consentCoachHistory}
                  disabled={busy || writing}
                  onSave={(on) => save(switchChange(read, 'consentCoachHistory', on))}
                />
                <p className="max-w-prose text-caption text-muted">{t('account.settings.turningOff')}</p>
              </div>
            )}

            <div className="space-y-1.5">
              <PressButton
                variant="quiet"
                label={t('account.settings.export.button')}
                workingLabel={t('account.dialog.working')}
                doneLabel={null}
                onPress={async () => {
                  setExportResult(null)
                  let reply: AccountReply | null
                  try {
                    reply = await actions.exportData()
                  } catch {
                    reply = null
                  }
                  const result = exportLine(reply)
                  setExportResult(result)
                  return result !== 'failed'
                }}
              />
              <p className="max-w-prose text-caption text-muted">{t('account.settings.export.description')}</p>
              {exportResult === 'saved' && <p className="text-caption text-ink2">{t('account.settings.export.saved')}</p>}
              {exportResult === 'failed' && (
                <p role="alert" className="break-words text-caption text-loss">
                  {t('account.settings.export.failed')}
                </p>
              )}
            </div>

            <div className="space-y-1.5">
              <PressButton
                variant="quiet"
                label={t('account.settings.signOut.button')}
                workingLabel={t('account.dialog.working')}
                doneLabel={null}
                onPress={async () => {
                  setSignOutFailure(null)
                  let reply: Saved
                  try {
                    reply = await actions.signOut()
                  } catch {
                    reply = { ok: false, error: t('account.welcome.error.signOutFailed') }
                  }
                  const sentence = failureOf(reply, t)
                  setSignOutFailure(sentence)
                  return sentence === null
                }}
              />
              <p className="max-w-prose text-caption text-muted">{t('account.settings.signOut.description')}</p>
              {signOutFailure && (
                <p role="alert" className="break-words text-caption text-loss">
                  {signOutFailure}
                </p>
              )}
            </div>

            <section aria-labelledby={deleteHeadingId} className="space-y-4 border-t border-line pt-5">
              <h3 id={deleteHeadingId} className="text-body font-medium text-ink">
                {t('account.settings.deleteHeading')}
              </h3>
              <div className="space-y-1.5">
                <Button variant="quiet" className="min-h-[44px]" aria-haspopup="dialog" onClick={() => open('history')}>
                  {t('account.settings.history.button')}
                </Button>
                <p className="max-w-prose text-caption text-muted">{t('account.settings.history.description')}</p>
                {historyResult !== null && (
                  <p className="max-w-prose text-caption text-ink2">
                    {t('account.settings.history.done', { count: historyResult, n: formatCount(historyResult) })}{' '}
                    {t('account.settings.history.removed')}
                  </p>
                )}
              </div>
              <div className="space-y-1.5">
                <Button variant="quiet" className="min-h-[44px]" aria-haspopup="dialog" onClick={() => open('account')}>
                  {t('account.settings.deleteAccount.button')}
                </Button>
                <p className="max-w-prose text-caption text-muted">{t('account.settings.deleteAccount.description')}</p>
              </div>
            </section>
          </>
        )}
      </div>

      <DeleteHistoryDialog
        open={dialog === 'history'}
        busy={busy}
        failure={dialog === 'history' ? failure : null}
        onCancel={history.cancel}
        onConfirm={() => void history.confirm()}
      />
      <DeleteAccountDialog
        open={dialog === 'account'}
        busy={busy}
        failure={dialog === 'account' ? failure : null}
        onCancel={account.cancel}
        onConfirm={() => void account.confirm()}
      />
      <ErrorsDialog
        open={dialog === 'errors'}
        busy={busy || writing}
        failure={errorsFailure}
        onCancel={errors?.cancel ?? close}
        onConfirm={() => void errors?.confirm()}
      />
    </Card>
  )
}
