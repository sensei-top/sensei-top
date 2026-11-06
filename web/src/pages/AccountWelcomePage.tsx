import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate } from 'react-router'
import { useShell } from '../bridge'
import { Button, Card, Disclosure, Segmented, TextLink } from '../components/ui'
import {
  canContinue,
  contribAnswer,
  introLines,
  opening,
  type Opening,
  policyDate,
  privacyUrl,
  profileChange,
  stepHint,
  stepsOf,
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

/** A step's detail, one click away under the step's control: what is kept,
 *  where and for how long. What a choice costs (the transfer box, a sent
 *  game that can't be deleted) is never put in here. */
function More({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  return (
    <Disclosure summary={t('account.welcome.more')}>
      <div className="max-w-prose space-y-1.5 text-body text-ink2">{children}</div>
    </Disclosure>
  )
}

/** A yes/no question's body, its pair of buttons, neither pressed until
 *  the user presses one, and its detail under them. The step's heading
 *  names a step's one question; a step that asks two gives each its own
 *  `heading`. */
function Question({
  heading,
  label,
  yes,
  no,
  answer,
  onAnswer,
  disabled,
  more,
  children,
}: {
  heading?: string
  label: string
  yes: string
  no: string
  answer: Answer
  onAnswer: (answer: boolean) => void
  disabled: boolean
  more: ReactNode
  children: ReactNode
}) {
  return (
    <div className="space-y-3">
      {heading && <h3 className="font-medium text-ink">{heading}</h3>}
      <div className="max-w-prose space-y-1.5 text-body text-ink2">{children}</div>
      <fieldset disabled={disabled}>
        <Segmented<Choice>
          label={label}
          value={choiceOf(answer)}
          options={[
            { value: 'yes', label: yes },
            { value: 'no', label: no },
          ]}
          onChange={(value) => onAnswer(value === 'yes')}
        />
      </fieldset>
      <More>{more}</More>
    </div>
  )
}

/** `/account/welcome`: the account's consent questions, after the first
 *  sign-in and after a new policy version, one step at a time (`stepsOf`).
 *  What it asks is fixed when the page loads (`opening`): the shell
 *  publishes the new profile before a save replies, and the screen must not
 *  change under the person. The steps live in the page, not the address:
 *  nothing is saved until Continue on the last one, so a reload starts the
 *  draft over. A user with nothing to answer goes Home. */
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
  const steps = stepsOf(kind, contributeShown)
  const [at, setAt] = useState(0)
  const [draft, setDraft] = useState<Draft>(open.draft)
  const [busy, setBusy] = useState<'continue' | 'leave' | null>(null)
  const [saved, setSaved] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const transferId = useId()
  const moved = useRef(false)
  // A step change moves the focus to the new heading, so a screen reader
  // reads the step that replaced the one left; not on the first render.
  useEffect(() => {
    if (moved.current) heading.current?.focus()
    moved.current = true
  }, [at])
  if (!shell || !app) return null

  const step = steps[at]
  const last = at === steps.length - 1
  const change = (part: Partial<Draft>) => setDraft((current) => ({ ...current, ...part }))
  const hint = stepHint(step, draft)
  const ready = hint === null && (!last || canContinue(kind, draft, contributeShown))
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

  const go = (by: number) => {
    setFailure(null)
    setAt((current) => current + by)
  }
  const hintText =
    hint === 'age'
      ? t('account.welcome.hint.age')
      : hint === 'transfer'
        ? t('account.welcome.hint.transfer')
        : hint === 'answer'
          ? t('account.welcome.hint.answer')
          : hint === 'answers'
            ? t('account.welcome.hint.answers')
            : null
  // What the account is opens the first step, whichever it is; where it is
  // kept, and that each answer can change later, lead that step's detail.
  const opener = at === 0 && intro !== null && (
    <div className="max-w-prose space-y-2 text-body text-ink2">
      {intro === 'intro' && <p>{t('account.welcome.intro')}</p>}
      {intro === 'changed' && <p>{t('account.welcome.changed', { date: policyDay, changes: t(changesKey) })}</p>}
    </div>
  )
  const kept = at === 0 && kind === 'returning' && (
    <p className="max-w-prose text-body text-ink2">{t('account.welcome.kept')}</p>
  )
  const openerMore = at === 0 && (
    <>
      <p>{t('account.welcome.stored')}</p>
      <p>{t('account.welcome.later')}</p>
    </>
  )

  return (
    <div className="mx-auto max-w-3xl">
      <Card>
        <div className="space-y-5">
          <div className="space-y-1">
            <p className="text-caption text-muted">{t('welcome.frame.step', { n: at + 1, total: steps.length })}</p>
            <h2 ref={heading} tabIndex={-1} className="font-display text-title text-ink outline-none">
              {t(`account.welcome.${step}.title`)}
            </h2>
          </div>

          {opener}
          {kept}

          {step === 'age' && (
            <div className="space-y-3">
              <label className="flex max-w-prose items-start gap-3 text-body text-ink">
                <input
                  type="checkbox"
                  className="mt-1 size-4 shrink-0 accent-accent"
                  checked={draft.age}
                  disabled={busy !== null}
                  onChange={(event) => change({ age: event.target.checked })}
                />
                <span>{t('account.welcome.age.label')}</span>
              </label>
              <More>
                {openerMore}
                <p>{t('account.welcome.age.small')}</p>
              </More>
            </div>
          )}

          {step === 'keep' && (
            <div className="space-y-6">
              <Question
                heading={t('account.welcome.sync.title')}
                label={t('account.welcome.sync.title')}
                yes={t('account.welcome.sync.yes')}
                no={t('account.welcome.sync.no')}
                answer={draft.sync}
                onAnswer={(sync) => change({ sync })}
                disabled={busy !== null}
                more={
                  <>
                    {openerMore}
                    <p>{t('account.welcome.sync.what')}</p>
                    <p>{t('account.welcome.sync.where')}</p>
                  </>
                }
              >
                <p>{t('account.welcome.sync.lead')}</p>
              </Question>
              <Question
                heading={t('account.welcome.coach.title')}
                label={t('account.welcome.coach.title')}
                yes={t('account.welcome.coach.yes')}
                no={t('account.welcome.coach.no')}
                answer={draft.coach}
                onAnswer={(coach) => change({ coach })}
                disabled={busy !== null}
                more={
                  <>
                    <p>{t('account.welcome.coach.kept')}</p>
                    <p>{t('account.welcome.coach.off')}</p>
                  </>
                }
              >
                <p>{t('account.welcome.coach.lead')}</p>
              </Question>
              <p className="text-body text-ink2">
                {t('account.welcome.policy.lead')}{' '}
                <TextLink href={privacyUrl(i18n.resolvedLanguage)}>
                  {t('account.welcome.policy.link', { date: policyDay })}
                </TextLink>
              </p>
            </div>
          )}

          {step === 'errors' && (
            <>
              <Question
                label={t('account.welcome.errors.title')}
                yes={t('account.welcome.errors.yes')}
                no={t('account.welcome.errors.no')}
                answer={draft.errors}
                onAnswer={(errors) => setDraft((current) => withErrors(current, errors))}
                disabled={busy !== null}
                more={
                  <>
                    <p>{t('account.welcome.errors.what')}</p>
                    <p>{t('account.welcome.errors.linked')}</p>
                  </>
                }
              >
                <p>{t('account.welcome.errors.lead')}</p>
              </Question>
              {draft.errors === true && (
                <section aria-labelledby={transferId} className="max-w-prose space-y-2 rounded-block bg-surface2 p-4 text-body text-ink2">
                  <h3 id={transferId} className="font-medium text-ink">{t('account.welcome.transfer.title')}</h3>
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
                </section>
              )}
            </>
          )}

          {step === 'contribute' && (
            <Question
              label={t('account.welcome.contribute.title')}
              yes={t('account.welcome.contribute.yes')}
              no={t('account.welcome.contribute.no')}
              answer={draft.contribute}
              onAnswer={(value) => change({ contribute: value })}
              disabled={busy !== null}
              more={
                <>
                  <p>{t('account.welcome.contribute.pool')}</p>
                  <p>{t('account.welcome.contribute.off')}</p>
                </>
              }
            >
              <p className="font-medium text-ink">{t('account.welcome.contribute.apart')}</p>
              {no && (
                <p>
                  {t('account.welcome.contribute.storedNo', {
                    date: formatDate(new Date(no.answeredAt), { dateStyle: 'long' }),
                  })}
                </p>
              )}
              <p>{t('account.welcome.contribute.lead')}</p>
              <p>{t('account.welcome.contribute.final')}</p>
            </Question>
          )}

          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              {at > 0 && (
                <Button variant="quiet" className="min-h-[44px]" disabled={busy !== null} onClick={() => go(-1)}>
                  {t('welcome.frame.back')}
                </Button>
              )}
              {last ? (
                <Button variant="primary" className="min-h-[44px]" disabled={busy !== null || !ready} onClick={onContinue}>
                  {busy === 'continue' ? t('account.welcome.working') : t('account.welcome.continue')}
                </Button>
              ) : (
                <Button variant="primary" className="min-h-[44px]" disabled={busy !== null || !ready} onClick={() => go(1)}>
                  {t('welcome.frame.next')}
                </Button>
              )}
            </div>
            {hintText && busy === null && <p className="text-caption text-muted">{hintText}</p>}
            {failure && (
              <p role="alert" className="break-words text-caption text-loss">
                {failure}
              </p>
            )}
          </div>

          <div className="space-y-1.5 border-t border-line pt-4">
            <Button variant="quiet" className="min-h-[44px]" disabled={busy !== null} onClick={onLeave}>
              {busy === 'leave'
                ? t('account.welcome.working')
                : kind === 'first'
                  ? t('account.welcome.decline')
                  : t('account.welcome.signOut')}
            </Button>
            {kind === 'first' && <p className="max-w-prose text-caption text-muted">{t('account.welcome.declineNote')}</p>}
          </div>
        </div>
      </Card>
    </div>
  )
}
