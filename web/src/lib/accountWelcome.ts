import type { AppSettings, ContribAnswer, Contribute, ProfileChange, ProfileState } from '../bridge'

/** The consent screen's address. */
export const ACCOUNT_WELCOME_PATH = '/account/welcome'

/** A question's answer; `null` until a button is pressed. */
export type Answer = boolean | null

/** What the screen holds before Continue. `transfer` is the box under
 *  "Send error reports" and means nothing unless `errors` is `true`. */
export type Draft = {
  age: boolean
  sync: Answer
  errors: Answer
  coach: Answer
  transfer: boolean
  contribute: Answer
}

/** `first`: no profile yet, nothing pre-selected. `returning`: the policy
 *  changed since the answers were given; they are pre-selected. */
export type Kind = 'first' | 'returning'

export function kindOf(profile: ProfileState): Kind {
  return profile.state === 'read' ? 'returning' : 'first'
}

/** The screen's first state: empty for a first sign-in; a returning user's
 *  earlier answers, the transfer box ticked when error reports were on. */
export function initialDraft(profile: ProfileState): Draft {
  if (profile.state === 'read') {
    return {
      age: false,
      sync: profile.consentSync,
      errors: profile.consentErrors,
      coach: profile.consentCoachHistory,
      transfer: profile.consentErrors,
      contribute: null,
    }
  }
  return { age: false, sync: null, errors: null, coach: null, transfer: false, contribute: null }
}

/** Sets the error-reports answer. Leaving `Send` unticks the transfer box,
 *  so a stale tick never rides along with a later `Send`. */
export function withErrors(draft: Draft, errors: boolean): Draft {
  return { ...draft, errors, transfer: errors ? draft.transfer : false }
}

/** "Help build the stats" is asked on a first sign-in only, and whenever
 *  this PC's answer is not a yes (unanswered, or a stored no). */
export function showContribute(kind: Kind, contribute: Contribute | null): boolean {
  return kind === 'first' && !contribute?.yes
}

/** The stored no whose date the block names; `null` for any other state. */
export function storedNo(kind: Kind, contribute: Contribute | null): Contribute | null {
  return showContribute(kind, contribute) && contribute && !contribute.yes ? contribute : null
}

/** Why Continue is off, as the one hint shown: `answers` while the age or
 *  an answer is missing (first sign-in), `transfer` while `Send` stands
 *  without the box. `null` when Continue is on. */
export function hintFor(kind: Kind, draft: Draft, contributeShown: boolean): 'answers' | 'transfer' | null {
  if (kind === 'first') {
    const missing =
      !draft.age ||
      draft.sync === null ||
      draft.errors === null ||
      draft.coach === null ||
      (contributeShown && draft.contribute === null)
    if (missing) return 'answers'
  }
  if (draft.errors === true && !draft.transfer) return 'transfer'
  return null
}

export function canContinue(kind: Kind, draft: Draft, contributeShown: boolean): boolean {
  return hintFor(kind, draft, contributeShown) === null
}

/** One step of the screen. `keep` asks the two things the account keeps
 *  at Supabase, the backup and the coach history; error reports have a step
 *  of their own, since the transfer box opens under them. */
export type Step = 'age' | 'keep' | 'errors' | 'contribute'

/** The steps shown, in order: a first sign-in starts with the age and ends
 *  with "Help build the stats" when it is asked; a returning user answers
 *  the account's questions only. */
export function stepsOf(kind: Kind, contributeShown: boolean): Step[] {
  const questions: Step[] = ['keep', 'errors']
  if (kind === 'returning') return questions
  return ['age', ...questions, ...(contributeShown ? (['contribute'] as const) : [])]
}

/** Why a step's Next (or the last step's Continue) is off, as the one hint
 *  shown: `age` until the box is ticked, `answers` until both of `keep`'s
 *  questions are answered, `answer` until a one-question step is,
 *  `transfer` while `Send` stands without the transfer box. `null` when the
 *  step is answered. */
export function stepHint(step: Step, draft: Draft): 'age' | 'answers' | 'answer' | 'transfer' | null {
  if (step === 'age') return draft.age ? null : 'age'
  if (step === 'keep') return draft.sync === null || draft.coach === null ? 'answers' : null
  const answer = draft[step]
  if (answer === null) return 'answer'
  if (step === 'errors' && answer && !draft.transfer) return 'transfer'
  return null
}

/** The profile write. `consentErrors` is `true` only with `Send` chosen and
 *  the transfer box ticked: the three together are the record of the
 *  transfer consent, so nothing else may ever write it. The age is sent on
 *  a first profile only. */
export function profileChange(kind: Kind, draft: Draft, policyVersion: string): ProfileChange {
  const change: ProfileChange = {
    consentSync: draft.sync === true,
    consentErrors: draft.errors === true && draft.transfer,
    consentCoachHistory: draft.coach === true,
    policyVersion,
  }
  if (kind === 'first') change.ageConfirmed = draft.age
  return change
}

/** The "Help build the stats" answer, or `null` when the block was not
 *  shown or not answered. The age box covers it. */
export function contribAnswer(draft: Draft, contributeShown: boolean, policyVersion: string): ContribAnswer | null {
  if (!contributeShown || draft.contribute === null) return null
  return { yes: draft.contribute, policyVersion, ageConfirmed: draft.age }
}

/** Whether the shell layout sends the user to the consent screen: signed
 *  in, with no profile or with answers given under an older policy version
 *  (a missing version counts as older). Never with no shell, no account, or
 *  a profile that could not be read, and never for answers given under a
 *  newer version than this install knows: asking again would write the
 *  older version back. Versions are `YYYY-MM-DD`, so strings compare. */
export function needsConsent(app: AppSettings | null | undefined, policyVersion: string): boolean {
  const account = app?.account
  if (!account?.available || !account.signedIn) return false
  const profile = account.profile
  if (!profile) return false
  if (profile.state === 'none') return true
  if (profile.state !== 'read') return false
  const given: string | null | undefined = profile.consentVersion
  return !given || given < policyVersion
}

/** What the screen asks, fixed when the page loads so the answers' own
 *  publication mid-save never changes it: `null` for a profile that is
 *  neither `none` nor `read`, which has nothing to ask. */
export type Opening = { kind: Kind; contributeShown: boolean; storedNo: Contribute | null; draft: Draft }

export function opening(profile: ProfileState | undefined, contribute: Contribute | null): Opening | null {
  if (!profile || (profile.state !== 'none' && profile.state !== 'read')) return null
  const kind = kindOf(profile)
  return {
    kind,
    contributeShown: showContribute(kind, contribute),
    storedNo: storedNo(kind, contribute),
    draft: initialDraft(profile),
  }
}

/** Which opening paragraph shows: the first sign-in's, the returning user's
 *  policy-change sentence, or none when no sentence was written for this
 *  version (the first sign-in's "Nothing is chosen for you" would
 *  contradict the pre-selected answers). */
export function introLines(kind: Kind, hasChanges: boolean): 'intro' | 'changed' | null {
  if (kind === 'first') return 'intro'
  return hasChanges ? 'changed' : null
}

/** The privacy page of the site, in the dashboard's language. */
export function privacyUrl(language: string | undefined): string {
  return language?.startsWith('pt') ? 'https://senseitop.com/pt-br/privacy/' : 'https://senseitop.com/privacy/'
}

/** The policy's date from its version (`YYYY-MM-DD`), as a local date so a
 *  zone behind UTC does not read it a day early; `null` when malformed. */
export function policyDate(version: string): Date | null {
  const found = /^(\d{4})-(\d{2})-(\d{2})$/.exec(version)
  return found ? new Date(Number(found[1]), Number(found[2]) - 1, Number(found[3])) : null
}
