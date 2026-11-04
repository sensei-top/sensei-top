import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router'
import { useShell } from '../bridge'
import { Button, Card, Segmented, TextLink } from '../components/ui'
import {
  canContinue,
  contribAnswer,
  hintFor,
  introLines,
  opening,
  type Opening,
  policyDate,
  privacyUrl,
  profileChange,
  withErrors,
  type Answer,
  type Draft,
} from '../lib/accountWelcome'
import { formatDate } from '../lib/format'
import { POLICY_VERSION } from '../lib/policy'
import { failureOf, settle } from '../lib/settings'
import { NotFoundPage } from './NotFoundPage'

type Choice = 'yes' | 'no' | 'unset'

function choiceOf(answer: Answer): Choice {
  return answer === null ? 'unset' : answer ? 'yes' : 'no'
}

/** A yes/no question: a pair of buttons, neither pressed until the user
 *  presses one. */
function Question({
  title,
  yes,
  no,
  answer,
  onAnswer,
  disabled,
  children,
}: {
  title: string
  yes: string
  no: string
  answer: Answer
  onAnswer: (answer: boolean) => void
  disabled: boolean
  children: ReactNode
}) {
  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="font-display text-title text-ink">{title}</h3>
      <div className="space-y-1.5 text-body text-ink2">{children}</div>
      <fieldset disabled={disabled}>
        <Segmented<Choice>
          label={title}
          value={choiceOf(answer)}
          options={[
            { value: 'yes', label: yes },
            { value: 'no', label: no },
          ]}
          onChange={(value) => onAnswer(value === 'yes')}
        />
      </fieldset>
    </section>
  )
}

/** `/account/welcome`: the account's consent questions, after the first
 *  sign-in and after a new policy version. What it asks is fixed when the
 *  page loads (`opening`): the shell publishes the new profile before a
 *  save replies, and the screen must not change under the person. A user
 *  with nothing to answer goes Home. */
export function AccountWelcomePage() {
  const shell = useShell()
  const account = shell?.app?.settings.account
  const [first] = useState<{ open: Opening | null }>(() => {
    const a = shell?.app?.settings.account
    if (!a?.available || !a.signedIn) return { open: null }
    return { open: opening(a.profile, shell?.app?.settings.contribute ?? null) }
  })
  if (!shell?.app || !account) return <NotFoundPage />
  if (!first.open) return <Navigate to="/" replace />
  return <Questions open={first.open} />
}

function Questions({ open }: { open: Opening }) {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const shell = useShell()
  const app = shell?.app
  const { kind, contributeShown, storedNo: no } = open
  const [draft, setDraft] = useState<Draft>(open.draft)
  const [busy, setBusy] = useState<'continue' | 'leave' | null>(null)
  const [saved, setSaved] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  if (!shell || !app) return null

  const change = (part: Partial<Draft>) => setDraft((current) => ({ ...current, ...part }))
  const hint = hintFor(kind, draft, contributeShown)
  const policy = policyDate(POLICY_VERSION)
  const policyDay = policy ? formatDate(policy, { dateStyle: 'long' }) : POLICY_VERSION
  const changesKey = `account.policyChanges.${POLICY_VERSION}`
  const intro = introLines(kind, i18n.exists(changesKey))

  const run = async (which: 'continue' | 'leave', work: () => Promise<string | null>) => {
    setBusy(which)
    setFailure(null)
    let failed: string | null
    try {
      failed = await work()
    } catch {
      failed = t('account.welcome.error.failed')
    }
    setBusy(null)
    if (failed) setFailure(failed)
    else void navigate('/', { replace: true })
  }

  const onContinue = () =>
    run('continue', async () => {
      if (!saved) {
        const reply = await app.account.setProfile(profileChange(kind, draft, POLICY_VERSION))
        if (!reply.ok) return t('account.welcome.error.failed')
        setSaved(true)
      }
      const answer = contribAnswer(draft, contributeShown, POLICY_VERSION)
      if (answer) return failureOf(await settle(shell.contribSet(answer), t), t)
      return null
    })

  const onLeave = () =>
    run('leave', async () => {
      if (kind === 'first') {
        const deleted = await app.account.deleteAccount()
        return deleted.ok ? null : t('account.welcome.error.declineFailed')
      }
      return failureOf(await settle(app.account.signOut(), t), t)
    })

  return (
    <div className="mx-auto max-w-3xl">
      <Card>
        <div className="space-y-5">
          <div className="space-y-2 text-body text-ink2">
            {intro === 'intro' && <p>{t('account.welcome.intro')}</p>}
            {intro === 'changed' && (
              <p>{t('account.welcome.changed', { date: policyDay, changes: t(changesKey) })}</p>
            )}
            <p>{t('account.welcome.stored')}</p>
            {kind === 'returning' && <p>{t('account.welcome.kept')}</p>}
          </div>

          {kind === 'first' && (
            <div className="space-y-1">
              <label className="flex items-start gap-3 text-body text-ink">
                <input
                  type="checkbox"
                  className="mt-1 size-4 shrink-0 accent-accent"
                  checked={draft.age}
                  disabled={busy !== null}
                  onChange={(event) => change({ age: event.target.checked })}
                />
                <span>{t('account.welcome.age.label')}</span>
              </label>
              <p className="pl-7 text-caption text-muted">{t('account.welcome.age.small')}</p>
            </div>
          )}

          <Question
            title={t('account.welcome.sync.title')}
            yes={t('account.welcome.sync.yes')}
            no={t('account.welcome.sync.no')}
            answer={draft.sync}
            onAnswer={(sync) => change({ sync })}
            disabled={busy !== null}
          >
            <p>{t('account.welcome.sync.what')}</p>
            <p>{t('account.welcome.sync.where')}</p>
          </Question>

          <Question
            title={t('account.welcome.errors.title')}
            yes={t('account.welcome.errors.yes')}
            no={t('account.welcome.errors.no')}
            answer={draft.errors}
            onAnswer={(errors) => setDraft((current) => withErrors(current, errors))}
            disabled={busy !== null}
          >
            <p>{t('account.welcome.errors.what')}</p>
            <p>{t('account.welcome.errors.linked')}</p>
            <p>{t('account.welcome.errors.either')}</p>
          </Question>

          {draft.errors === true && (
            <Card elevation={2} title={t('account.welcome.transfer.title')}>
              <div className="space-y-2 text-body text-ink2">
                <p>{t('account.welcome.transfer.law')}</p>
                <p>{t('account.welcome.transfer.ip')}</p>
                <label className="flex items-start gap-3 text-ink">
                  <input
                    type="checkbox"
                    className="mt-1 size-4 shrink-0 accent-accent"
                    checked={draft.transfer}
                    disabled={busy !== null}
                    onChange={(event) => change({ transfer: event.target.checked })}
                  />
                  <span>{t('account.welcome.transfer.agree')}</span>
                </label>
                <p className="text-caption text-muted">{t('account.welcome.transfer.withdraw')}</p>
              </div>
            </Card>
          )}

          <Question
            title={t('account.welcome.coach.title')}
            yes={t('account.welcome.coach.yes')}
            no={t('account.welcome.coach.no')}
            answer={draft.coach}
            onAnswer={(coach) => change({ coach })}
            disabled={busy !== null}
          >
            <p>{t('account.welcome.coach.kept')}</p>
            <p>{t('account.welcome.coach.off')}</p>
          </Question>

          <p className="text-body text-ink2">
            {t('account.welcome.policy.lead')}{' '}
            <TextLink href={privacyUrl(i18n.resolvedLanguage)}>
              {t('account.welcome.policy.link', { date: policyDay })}
            </TextLink>
          </p>

          {contributeShown && (
            <div className="border-t border-line pt-5">
              <Question
                title={t('account.welcome.contribute.title')}
                yes={t('account.welcome.contribute.yes')}
                no={t('account.welcome.contribute.no')}
                answer={draft.contribute}
                onAnswer={(value) => change({ contribute: value })}
                disabled={busy !== null}
              >
                {no && (
                  <p>
                    {t('account.welcome.contribute.storedNo', {
                      date: formatDate(new Date(no.answeredAt), { dateStyle: 'long' }),
                    })}
                  </p>
                )}
                <p>{t('account.welcome.contribute.apart')}</p>
                <p>{t('account.welcome.contribute.what')}</p>
                <p>{t('account.welcome.contribute.pool')}</p>
                <p>{t('account.welcome.contribute.final')}</p>
                <p>{t('account.welcome.contribute.off')}</p>
              </Question>
            </div>
          )}

          <div className="space-y-3">
            {hint && (
              <p className="text-caption text-muted">
                {hint === 'answers' ? t('account.welcome.hint.answers') : t('account.welcome.hint.transfer')}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" disabled={busy !== null || !canContinue(kind, draft, contributeShown)} onClick={onContinue}>
                {busy === 'continue' ? t('account.welcome.working') : t('account.welcome.continue')}
              </Button>
              <Button variant="quiet" disabled={busy !== null} onClick={onLeave}>
                {busy === 'leave'
                  ? t('account.welcome.working')
                  : kind === 'first'
                    ? t('account.welcome.decline')
                    : t('account.welcome.signOut')}
              </Button>
            </div>
            {failure && (
              <p role="alert" className="break-words text-caption text-loss">
                {failure}
              </p>
            )}
            {kind === 'first' && <p className="text-caption text-muted">{t('account.welcome.declineNote')}</p>}
          </div>
        </div>
      </Card>
    </div>
  )
}
