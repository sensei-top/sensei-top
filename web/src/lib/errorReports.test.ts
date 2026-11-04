import { describe, expect, it, vi } from 'vitest'
import { forwardErrors, reportBoundary, sentKey, toReport } from './errorReports'

describe('a thrown value as a report', () => {
  it('keeps an Error whole', () => {
    const error = new TypeError('boom')
    expect(toReport(error)).toEqual({ name: 'TypeError', message: 'boom', stack: error.stack ?? null })
  })
  it('takes a string as the message and names anything else', () => {
    expect(toReport('plain')).toEqual({ name: 'Error', message: 'plain', stack: null })
    expect(toReport(42).message).toBe('Non-error value rejected')
  })
})

describe('forwarding the page\'s uncaught errors', () => {
  function target() {
    const handlers: Record<string, (event: unknown) => void> = {}
    return { handlers, addEventListener: (type: string, fn: (event: unknown) => void) => void (handlers[type] = fn) }
  }
  it('sends an error event and a rejection through reportError', async () => {
    const report = vi.fn(async (_error: { message: string }) => true)
    const t = target()
    forwardErrors(report, t as unknown as Window)
    t.handlers.error({ error: new Error('one'), message: 'one' })
    t.handlers.unhandledrejection({ reason: 'two' })
    await Promise.resolve()
    await Promise.resolve()
    expect(report.mock.calls.map(([r]) => r.message)).toEqual(['one', 'two'])
  })
  it('listens to nothing without reportError, and survives one that throws', async () => {
    const none = target()
    forwardErrors(undefined, none as unknown as Window)
    // `undefined` falls back to the global, which a test run has none of.
    expect(Object.keys(none.handlers)).toEqual([])
    const t = target()
    const failing = vi.fn(async (_error: { message: string }): Promise<boolean> => {
      throw new Error('bridge down')
    })
    forwardErrors(failing, t as unknown as Window)
    t.handlers.error({ message: 'x' })
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(failing).toHaveBeenCalledTimes(1)
  })
})

describe('the boundary reporting', () => {
  it('answers sent when the shell captured it, notSent when it did not', async () => {
    expect(await reportBoundary(new Error('a'), async () => true)).toBe('sent')
    expect(await reportBoundary(new Error('b'), async () => false)).toBe('notSent')
  })
  it('answers notSent with no reportError, or one that throws', async () => {
    expect(await reportBoundary(new Error('c'), undefined)).toBe('notSent')
    expect(
      await reportBoundary(new Error('d'), async () => {
        throw new Error('down')
      }),
    ).toBe('notSent')
  })
  it('answers pending when the shell does not answer in time', async () => {
    expect(await reportBoundary(new Error('e'), () => new Promise<boolean>(() => {}), 5)).toBe('pending')
  })
  it('reports one error once, however often the screen mounts', async () => {
    const report = vi.fn(async () => true)
    const error = new Error('f')
    await reportBoundary(error, report)
    await reportBoundary(error, report)
    expect(report).toHaveBeenCalledTimes(1)
  })
  it('names a catalogue key per answer', () => {
    expect(sentKey('sent')).toBe('report.error.sent')
    expect(sentKey('notSent')).toBe('report.error.notSent')
    expect(sentKey('pending')).toBe('report.error.pending')
  })
})
