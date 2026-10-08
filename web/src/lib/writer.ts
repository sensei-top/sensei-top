/**
 * Who writes a report, read from what the API says of a key: a key of the
 * viewer's, or nobody, and the prompt is there to copy.
 */

/** Who writes a report. */
export type Writer = { by: 'nobody' } | { by: 'key' }

/** Who writes a report. `status` is the API's answer on the key,
 *  `undefined` or `null` before it answers. */
export function writerFrom(status: { configured: boolean } | null | undefined): Writer {
  return status?.configured ? { by: 'key' } : { by: 'nobody' }
}
