import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { AccountActions, AccountProvider } from '../../bridge'
import { Button } from '../ui'
import { attemptGuard } from './accountLogic'

/** The two sign-in buttons, both off while one waits on the browser, then
 *  `children`, the wait's note and a failed sign-in's sentence. Settings →
 *  Account draws it signed out, and so does the welcome's first step, for
 *  someone bringing back a backed-up history. `onStart` runs at each press. */
export function SignInButtons({
  signIn,
  onStart,
  variant = 'primary',
  children,
}: {
  signIn: AccountActions['signIn']
  onStart?: () => void
  variant?: 'primary' | 'secondary'
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const [waiting, setWaiting] = useState<AccountProvider | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [attempts] = useState(attemptGuard)

  const press = async (provider: AccountProvider) => {
    const current = attempts.begin()
    setWaiting(provider)
    setFailure(null)
    onStart?.()
    let message: string | null = null
    try {
      const reply = await signIn(provider)
      if (!reply.ok) message = reply.message.trim() || t('account.settings.signInFailed')
    } catch {
      message = t('account.settings.signInFailed')
    }
    // Both buttons are off while one waits; the guard still keeps a stale
    // answer from landing over a newer press.
    if (!current()) return
    setWaiting(null)
    setFailure(message)
  }

  return (
    <>
      <div className="flex flex-wrap gap-3">
        {(['google', 'discord'] as const).map((which) => (
          <Button
            key={which}
            variant={variant}
            className="min-h-[44px]"
            disabled={waiting !== null}
            onClick={() => void press(which)}
          >
            {waiting === which
              ? t('account.settings.signingIn')
              : which === 'google'
                ? t('account.settings.signInGoogle')
                : t('account.settings.signInDiscord')}
          </Button>
        ))}
      </div>
      {children}
      {waiting && <p className="max-w-prose text-caption text-muted">{t('account.settings.waiting')}</p>}
      {failure && (
        <p role="alert" className="break-words text-caption text-loss">
          {failure}
        </p>
      )}
    </>
  )
}
