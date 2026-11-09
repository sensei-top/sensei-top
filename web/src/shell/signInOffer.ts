import { useTranslation } from 'react-i18next'
import { useShell, type Shell } from '../bridge'
import { settle } from '../lib/settings'

/** Whether the sign-in offer shows: the build has an account, nobody is
 *  signed in, the welcome was seen, and the offer was not dismissed. Each
 *  condition false hides it; a browser has no shell and no offer. */
export function signInOffered(shell: Shell | null): boolean {
  const app = shell?.app?.settings
  if (!app) return false
  const account = app.account
  return account.available && !account.signedIn && app.onboarded && !app.signInDismissed
}

/** The sign-in offer's state and its dismissal, which the rail item and
 *  Home's line share: dismissing either sets the flag and both go. */
export function useSignInOffer(): { offered: boolean; dismiss: () => void } {
  const shell = useShell()
  const { t } = useTranslation()
  return {
    offered: signInOffered(shell),
    // A failed write leaves the offer showing, the safe side.
    dismiss: () => {
      const set = shell?.app?.set
      if (set) void settle(Promise.resolve().then(() => set({ signInDismissed: true })), t)
    },
  }
}
