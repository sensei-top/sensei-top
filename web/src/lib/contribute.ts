import type { Contribute, ContribAnswer, Saved } from '../bridge'
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
