import type { AppSettings, Contribute, ContribAnswer, Saved } from '../bridge'
import type { TFunction } from '../i18n'
import { settle } from './settings'

/** Whether "Help build the stats" is put to the person when a run begins:
 *  the build can upload and nothing is stored yet. */
export function contribAskedOnWelcome(canContribute: boolean, stored: Contribute | null): boolean {
  return canContribute && stored === null
}

/** Whether Go to Home waits on this question: it was asked when the run
 *  began and neither the shell's stored answer nor a press of this run has
 *  answered it. */
export function contribWaits(asked: boolean, stored: Contribute | null, picked: boolean | null): boolean {
  return asked && stored === null && picked === null
}

/** The answer saved so far, from the shell's or from this run's press. */
export function savedAnswer(stored: Contribute | null, picked: boolean | null): boolean | null {
  return stored ? stored.yes : picked
}

/** What to send for a press. A yes needs the age box; `null` is "not
 *  allowed". A no keeps a stored `ageConfirmed` and says `false` when
 *  nothing is stored, so a no never claims an age the person did not confirm. */
export function answerFor(
  yes: boolean,
  ageTicked: boolean,
  stored: Contribute | null,
  version: string,
): ContribAnswer | null {
  if (yes) return ageTicked ? { yes: true, policyVersion: version, ageConfirmed: true } : null
  return {
    yes: false,
    policyVersion: stored?.policyVersion ?? version,
    ageConfirmed: stored?.ageConfirmed ?? false,
  }
}

/** The age box: a saved yes keeps it ticked and locked; it is locked while a save runs. */
export function ageBox(age: boolean, saved: boolean | null, saving: boolean): { checked: boolean; disabled: boolean } {
  return { checked: age || saved === true, disabled: saved === true || saving }
}

/** Whether an answer button shows pressed: it is the saved answer. */
export function isPressed(saved: boolean | null, yes: boolean): boolean {
  return saved === yes
}

/** The caption under the buttons: only the first that applies. `ageMissing`
 *  is a yes pressed without the box and `age` is the box now, so ticking it
 *  clears the hint; `waiting` is Go to Home waiting. */
export function hintFor(ageMissing: boolean, age: boolean, waiting: boolean): 'age' | 'waitsWelcome' | null {
  if (ageMissing && !age) return 'age'
  return waiting ? 'waitsWelcome' : null
}

/** The key of the failure line: a no that failed after a yes was saved
 *  leaves the yes sending, and says so. */
export function failureKey(yes: boolean, savedYes: boolean | null): 'notSaved' | 'stillSending' {
  return !yes && savedYes === true ? 'stillSending' : 'notSaved'
}

export type Pressed =
  | { kind: 'needAge' }
  | { kind: 'saved'; yes: boolean }
  | { kind: 'failed'; line: string; key: 'notSaved' | 'stillSending' }

/** One press of an answer button. A yes without the age box saves nothing
 *  and calls nothing; a refused or rejected call is a failure, never a throw. */
export async function pressAnswer(
  yes: boolean,
  ageTicked: boolean,
  stored: Contribute | null,
  savedYes: boolean | null,
  version: string,
  save: ((answer: ContribAnswer) => Promise<Saved>) | undefined,
  t: TFunction,
): Promise<Pressed> {
  const answer = answerFor(yes, ageTicked, stored, version)
  if (!answer) return { kind: 'needAge' }
  const key = failureKey(yes, savedYes)
  const saved = save ? await settle(Promise.resolve().then(() => save(answer)), t) : ({ ok: false, error: '' } as const)
  return saved.ok ? { kind: 'saved', yes } : { kind: 'failed', line: t(`contribute.failure.${key}`), key }
}

/** The one-time page's address. */
export const CONTRIBUTE_PATH = '/contribute'

/** The addresses the shell never sends the one-time page over: onboarding,
 *  the account's consent screen and the page itself. */
export const CONTRIBUTE_KEEPS = ['/welcome', '/account/welcome', CONTRIBUTE_PATH] as const

/** Whether the one-time page is due: the build can upload, onboarding is
 *  done, nothing is stored and the page was never shown. The account's
 *  consent screen (`consentDue`) goes first, and a signed-in account whose
 *  profile is not read yet makes the page wait: consent cannot be decided,
 *  and opening now would spend the one ask unseen. */
export function contribPageDue(
  app: Pick<AppSettings, 'canContribute' | 'contribAsked' | 'contribute' | 'onboarded' | 'account'> | null | undefined,
  consentDue: boolean,
): boolean {
  if (!app || consentDue) return false
  const account = app.account
  if (account?.available && account.signedIn && (!account.profile || account.profile.state === 'unknown')) return false
  return app.canContribute && !app.contribAsked && app.contribute === null && app.onboarded
}

/** Whether a switch turned on needs the dialog: nothing is stored, the
 *  stored answer lacks the age confirmation, or it was given under an older
 *  policy. Versions are `YYYY-MM-DD`, so strings compare. */
export function dialogNeeded(stored: Contribute | null, version: string): boolean {
  return !stored || !stored.ageConfirmed || stored.policyVersion < version
}

/** The yes a turn-on saves without the dialog. */
export function turnOnAnswer(version: string): ContribAnswer {
  return { yes: true, policyVersion: version, ageConfirmed: true }
}

/** The no a turn-off saves: the stored age confirmation and version stay. */
export function turnOffAnswer(stored: Contribute | null, version: string): ContribAnswer {
  return answerFor(false, false, stored, version) as ContribAnswer
}

/** The state line under the switch. `visit` is what this visit did: a
 *  turn-on without the dialog, or a turn-off. */
export type StateKey = 'turnedOn' | 'turnedOff' | 'on' | 'off' | 'unanswered'
export function stateKey(stored: Contribute | null, visit: 'on' | 'off' | null): StateKey {
  if (visit === 'on') return 'turnedOn'
  if (visit === 'off') return 'turnedOff'
  if (!stored) return 'unanswered'
  return stored.yes ? 'on' : 'off'
}

/** The failure line of a switch: `on` is the turn that failed. */
export function settingsFailureKey(turnedOn: boolean): 'turnOn' | 'turnOff' {
  return turnedOn ? 'turnOn' : 'turnOff'
}

/** One save of an answer; a refused or rejected call is `false`, never a throw. */
export async function submitAnswer(
  answer: ContribAnswer,
  save: ((answer: ContribAnswer) => Promise<Saved>) | undefined,
  t: TFunction,
): Promise<boolean> {
  if (!save) return false
  return (await settle(Promise.resolve().then(() => save(answer)), t)).ok
}
