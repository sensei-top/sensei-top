import { useEffect, useState } from 'react'
import { isRouteErrorResponse } from 'react-router'
import { readShellGlobal, type RendererErrorReport, type ShellReports } from '../bridge'

type ReportError = ShellReports['reportError']

/** How long the error screen waits for the shell's answer before it words
 *  the line as still pending. */
export const ANSWER_WAIT_MS = 3000

/** What the screen says about whether the error went: the shell's answer,
 *  or `pending` while it has not come (or the page could not wait for it). */
export type Sent = 'sent' | 'notSent' | 'pending'

/** A thrown value as the report the shell takes. A route's own response
 *  (a thrown `Response`) has no stack; it is named by its status. */
export function toReport(value: unknown): RendererErrorReport {
  if (isRouteErrorResponse(value)) {
    return { name: 'RouteError', message: `${value.status} ${value.statusText}`.trim(), stack: null }
  }
  const error = value instanceof Error ? value : null
  return {
    name: error?.name ?? 'Error',
    message: error ? error.message : typeof value === 'string' ? value : 'Non-error value rejected',
    stack: error?.stack ?? null,
  }
}

/** Inside the desktop shell the page's uncaught errors go to the shell, which
 *  drops them unless the user said yes to error reports. A plain browser has
 *  no bridge and this does nothing. An error a React boundary catches does
 *  not reach `window`'s `error` event: `reportBoundary` sends that one. */
export function forwardErrors(
  report: ReportError | undefined = readShellGlobal()?.reportError,
  target: Pick<Window, 'addEventListener'> = window,
): void {
  if (!report) return
  const send = (value: unknown): void => {
    void Promise.resolve()
      .then(() => report(toReport(value)))
      .catch(() => {})
  }
  target.addEventListener('error', (event) => send((event as ErrorEvent).error ?? (event as ErrorEvent).message))
  target.addEventListener('unhandledrejection', (event) => send((event as PromiseRejectionEvent).reason))
}

const asked = new WeakMap<object, Promise<Sent>>()

/** Reports an error the boundary caught, once per thrown object however many
 *  times the screen mounts. A thrown primitive (a string, say) can't be
 *  remembered, and may be reported again when StrictMode remounts in
 *  development. Resolves with what the line should say. No `reportError`,
 *  `false`, or a call that throws is `notSent`; no answer within `waitMs` is
 *  `pending`. Never rejects. */
export function reportBoundary(
  value: unknown,
  report: ReportError | undefined = readShellGlobal()?.reportError,
  waitMs: number = ANSWER_WAIT_MS,
): Promise<Sent> {
  if (!report) return Promise.resolve('notSent')
  const cached = typeof value === 'object' && value !== null ? asked.get(value) : undefined
  if (cached) return cached
  const answer = Promise.resolve()
    .then(() => report(toReport(value)))
    .then((captured): Sent => (captured === true ? 'sent' : 'notSent'))
    .catch((): Sent => 'notSent')
  let timer: ReturnType<typeof setTimeout> | undefined
  const waited = new Promise<Sent>((resolve) => {
    timer = setTimeout(() => resolve('pending'), waitMs)
  })
  const result = Promise.race([answer, waited]).finally(() => clearTimeout(timer))
  if (typeof value === 'object' && value !== null) asked.set(value, result)
  return result
}

/** The catalogue key of the line saying whether the error was sent. */
export function sentKey(sent: Sent): string {
  return `report.error.${sent}`
}

/** The error's message for the report dialog's first line. */
export function messageOf(value: unknown): string {
  return toReport(value).message
}

/** Reports `error` once and follows the answer: `pending` until it comes. */
export function useBoundaryReport(error: unknown): Sent {
  const [sent, setSent] = useState<Sent>('pending')
  useEffect(() => {
    let live = true
    void reportBoundary(error).then((answer) => {
      if (live) setSent(answer)
    })
    return () => {
      live = false
    }
  }, [error])
  return sent
}
