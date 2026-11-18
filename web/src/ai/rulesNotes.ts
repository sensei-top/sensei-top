import { useCallback } from 'react'
import { post, put } from '../api'
import { POLICY_VERSION } from '../lib/policy'
import type { AccountState, CoachResult, Shell } from '../bridge'
import { useShell } from '../bridge'
import type { components } from '../types/api'

/** What a feature asks the API about: `POST /api/rules-questions`' body. */
export type RulesRequest = components['schemas']['RulesQuestionsIn']

/** `stored`: notes written. `reason`: why some or all are missing, `null`
 *  when nothing is. `gated`: the reason came from `gateReason`, before
 *  anything was asked: the player's own state (`unavailable`, `signedOut`,
 *  `consent`, `notesOff`), not a missing answer. A coach's `signedOut` is
 *  not gated. */
export type NotesOutcome = { stored: number; reason: string | null; gated: boolean }

/** Whether the card says "Written without rules notes.": something was
 *  asked and not answered. */
export function notesMissing(outcome: NotesOutcome): boolean {
  return outcome.reason !== null && !outcome.gated
}

/** Runs `press` (if any), then `act` with its result, whatever the press
 *  does: a rejection gives `act(null)`. Never throws on the press's account.
 *  Resolves to whether the notes are missing: true after a rejection. */
export async function pressThenAct<T>(
  press: (() => Promise<T>) | undefined,
  missingOf: (result: T) => boolean,
  act: (result: T | null) => void,
): Promise<boolean> {
  let result: T | null = null
  let missing = false
  if (press) {
    try {
      result = await press()
      missing = missingOf(result)
    } catch {
      missing = true
    }
  }
  act(result)
  return missing
}

/** Why the press does not ask at all, or `null` when it may. Consent is the
 *  profile's version at or after the policy's (`YYYY-MM-DD` compares as a
 *  date) and the Terms of Use agreed to (`termsAgreedAt` set; Settings can
 *  raise the version without it); a profile with no `rulesNotes` field reads as on. */
export function gateReason(shell: Shell | null, account: AccountState | undefined, policyVersion: string = POLICY_VERSION): string | null {
  if (!shell?.coach) return 'unavailable'
  if (!account?.available || !account.signedIn) return 'signedOut'
  const profile = account.profile
  if (profile?.state !== 'read' || profile.consentVersion < policyVersion || !profile.termsAgreedAt) return 'consent'
  if (profile.rulesNotes === false) return 'notesOff'
  return null
}

/** Asks the coach for the notes `request`'s prompt lacks and stores them.
 *  Never throws: a failure is a `reason`, and the caller's generate or copy
 *  goes on. Only questions the API says are unanswered are asked, and only
 *  an `answered` or `refused` outcome with a rules version is stored. */
export async function askRulesNotes(
  request: RulesRequest,
  shell: Shell | null,
  account: AccountState | undefined,
): Promise<NotesOutcome> {
  const skipped = gateReason(shell, account)
  if (skipped !== null) return { stored: 0, reason: skipped, gated: true }
  try {
    const listed = await post<components['schemas']['RulesQuestionsOut']>('/api/rules-questions', request)
    const open = listed.questions.filter((q) => !q.answered).map((q) => q.question)
    if (open.length === 0) return { stored: 0, reason: null, gated: false }
    const results: CoachResult[] = await (shell as Shell).coach!.ask(open)
    let reason: string | null = null
    const notes: components['schemas']['RulesNoteIn'][] = []
    for (const r of results) {
      if (!r.ok) {
        reason ??= r.reason
      } else if ((r.outcome === 'answered' || r.outcome === 'refused') && r.rules_version) {
        notes.push({
          question: r.question,
          rules_version: r.rules_version,
          outcome: r.outcome,
          verdict: r.verdict,
          explanation: r.explanation,
          citations: r.citations ?? [],
          confidence: r.confidence,
          out_of_scope: r.out_of_scope ?? false,
        })
      } else {
        reason ??= 'tryAgain'
      }
    }
    if (notes.length > 0) await put('/api/rules-notes', { notes })
    return { stored: notes.length, reason, gated: false }
  } catch (exc) {
    console.debug('rules notes: not written', exc)
    return { stored: 0, reason: 'failed', gated: false }
  }
}

/** The press for one request: call it before a generate or a copy. The
 *  reason goes to the debug log whatever it is. */
export function useRulesNotesPress(request: RulesRequest): () => Promise<NotesOutcome> {
  const shell = useShell()
  const account = shell?.app?.settings.account
  const key = JSON.stringify(request)
  return useCallback(async () => {
    const outcome = await askRulesNotes(JSON.parse(key) as RulesRequest, shell, account)
    if (outcome.reason !== null) console.debug('rules notes:', outcome.reason)
    return outcome
  }, [key, shell, account])
}
