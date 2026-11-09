import { createContext, useContext } from 'react'
import type { AccountState, ReportOutcome, ShellReports } from '../bridge'
import { POLICY_VERSION } from './policy'
import { formatShortDay, parseTimestamp } from './time'

/** The longest report the dialog sends, in characters; the shell refuses more. */
export const REPORT_LIMIT = 4000
/** The counter appears from here, so it is quiet until it matters. */
export const COUNTER_FROM = 3600
/** An error's message is cut here, so a stack pasted into a message cannot
 *  crowd out what the person writes. */
const MESSAGE_CAP = 500

/** What the dialog is drafting. `detail` is the worded technical-detail line
 *  sent under the text, `''` when the dialog was not opened from an error. */
export type ReportDraft = {
  text: string
  attachLog: boolean
  agreed: boolean
  detail?: string
  /** `bug` when absent. An `idea` never sends the log or the detail, whatever the draft holds. */
  kind?: ReportKind
  /** The address path the dialog was opened on; `null` where there is none. */
  page?: string | null
  /** The match whose page it was opened on; `null` elsewhere. */
  matchId?: string | null
}

export type ReportKind = 'bug' | 'idea'

/** The address path a report is sent from, as the shell accepts it: a `/…`
 *  path with no query or fragment; `null` for anything else. */
export function pageOf(pathname: string | null | undefined): string | null {
  if (!pathname || !pathname.startsWith('/') || /[?#]/.test(pathname)) return null
  return pathname
}

/** The match a path is the page of (`/matches/:id` and its views), else `null`. */
export function matchIdOf(params: { id?: string } | undefined, pathname: string): string | null {
  return params?.id && /^\/matches\/[^/]+(\/|$)/.test(pathname) ? params.id : null
}

/** The "About: the match of …" line a match's page shows, shown and never sent.
 *  The fuller key needs both the deck and the opponent; one missing falls back
 *  to the date alone. `null` when the match has no start time to name it by. */
export function aboutOf(
  match: { started_at?: string | null; deck_name?: string | null; opponent_label?: string | null },
  now: number,
): { key: 'report.dialog.about.match' | 'report.dialog.about.matchDate'; values: Record<string, string> } | null {
  const started = parseTimestamp(match.started_at)
  if (started == null) return null
  const date = formatShortDay(started, now)
  return match.deck_name && match.opponent_label
    ? { key: 'report.dialog.about.match', values: { date, deck: match.deck_name, opponent: match.opponent_label } }
    : { key: 'report.dialog.about.matchDate', values: { date } }
}

/** The first thing that keeps Send report disabled, in the order the hint names them. */
export type Blocker = 'noText' | 'tooLong' | 'notAgreed'

export function blockerOf(draft: Pick<ReportDraft, 'text' | 'agreed'>): Blocker | null {
  if (draft.text.trim() === '') return 'noText'
  if (draft.text.length > REPORT_LIMIT) return 'tooLong'
  if (!draft.agreed) return 'notAgreed'
  return null
}

/** The error's message as one line, cut to `MESSAGE_CAP`: shown apart from
 *  the field as a technical detail and sent under the text. `''` when the
 *  dialog was not opened from an error. */
export function detailOf(message: string | null): string {
  return (message ?? '').replace(/\s+/g, ' ').trim().slice(0, MESSAGE_CAP)
}

/** What is sent: the person's text, then the detail line after a blank line
 *  when there is one and the two fit the limit together; the text alone when
 *  they would not, since the text is the person's own. */
export function reportText(text: string, detail: string | undefined): string {
  const own = text.trim()
  if (!detail) return own
  const joined = `${own}\n\n${detail}`
  return joined.length <= REPORT_LIMIT ? joined : own
}

const OUTCOMES: readonly ReportOutcome[] = ['sent', 'sent-without-log', 'unavailable', 'invalid', 'failed']

/** The one place a report reaches the bridge, and only when sent. A call that
 *  throws, or answers with a word this page does not know, is `failed`; a
 *  draft the dialog would have blocked is `invalid` and calls nothing. */
export async function sendReport(call: ShellReports['reportProblem'] | undefined, draft: ReportDraft): Promise<ReportOutcome> {
  if (!call) return 'unavailable'
  if (blockerOf(draft) !== null) return 'invalid'
  try {
    const idea = draft.kind === 'idea'
    const outcome = await call({
      text: reportText(draft.text, idea ? undefined : draft.detail),
      attachLog: idea ? false : draft.attachLog,
      kind: draft.kind ?? 'bug',
      page: draft.page ?? null,
      matchId: draft.matchId ?? null,
    })
    return OUTCOMES.includes(outcome) ? outcome : 'failed'
  } catch {
    return 'failed'
  }
}

/** What the Send button does. `dismissed.current` is set by the dialog when
 *  it was closed while a send ran; a send starts it over, and only a failed
 *  send reopens the dialog. The previous outcome is cleared as a send starts. */
export function sendControls({
  call,
  draft,
  dismissed,
  setBusy,
  setOutcome,
  reopen,
}: {
  call: ShellReports['reportProblem'] | undefined
  draft: () => ReportDraft
  dismissed: { current: boolean }
  setBusy: (busy: boolean) => void
  setOutcome: (outcome: ReportOutcome | null) => void
  reopen: () => void
}): { send: () => Promise<void> } {
  return {
    send: async () => {
      setBusy(true)
      setOutcome(null)
      dismissed.current = false
      const outcome = await sendReport(call, draft())
      setBusy(false)
      setOutcome(outcome)
      if (!wasSent(outcome) && dismissed.current) reopen()
    },
  }
}

/** A report that went: the form gives way to its line and a Close button. */
export function wasSent(outcome: ReportOutcome): boolean {
  return outcome === 'sent' || outcome === 'sent-without-log'
}

/** The catalogue key of an outcome's line; an idea that went has its own thanks. */
export function outcomeKey(outcome: ReportOutcome, kind: ReportKind = 'bug'): string {
  if (kind === 'idea' && outcome === 'sent') return 'report.dialog.result.sentIdea'
  return `report.dialog.result.${outcome === 'sent-without-log' ? 'sentWithoutLog' : outcome}`
}

/** Whether the report will carry an account ID: the shell's account is signed in. */
export function signedInOf(account: AccountState | undefined): boolean {
  return account?.available === true && account.signedIn
}

/** Whether the error-reports consent already covers the transfer, so the
 *  dialog shows a line instead of the box: signed in with the profile read,
 *  error reports on, and the yes given under the current policy or a later
 *  one (`YYYY-MM-DD` strings compare as dates). Signed out, an unread
 *  profile or an older yes never skips the box. */
export function standingConsentOf(account: AccountState | undefined, policyVersion: string = POLICY_VERSION): boolean {
  if (!account?.available || !account.signedIn) return false
  const profile = account.profile
  return profile?.state === 'read' && profile.consentErrors && profile.consentVersion >= policyVersion
}

/** What a page that can open the dialog is given: `message` is an error's,
 *  shown and sent as a technical detail. `null` where no shell sends reports. */
export type ReportOpener = { open: (message: string | null) => void }

export const ReportProblemContext = createContext<ReportOpener | null>(null)

export function useReportProblem(): ReportOpener | null {
  return useContext(ReportProblemContext)
}
