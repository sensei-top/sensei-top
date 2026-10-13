import { formatFixed } from './format'

/** A size in bytes as a person reads it, where 1 MB is 1,000,000 bytes.
 *  Under 1 GB it is megabytes, to one decimal under 100 MB ("41.3 MB") and
 *  whole from there ("412 MB"), and never less than "0.1 MB". From 1 GB it
 *  is gigabytes to one decimal, with a ".0" dropped ("1.2 GB", "2 GB"). */
export function sizeOf(bytes: number): string {
  const megabytes = bytes / 1_000_000
  if (Math.round(megabytes) >= 1000) return `${Math.round(bytes / 100_000_000) / 10} GB`
  if (megabytes < 0.1) return '0.1 MB'
  const tenths = Math.round(megabytes * 10) / 10
  return tenths >= 100 ? `${Math.round(megabytes)} MB` : `${formatFixed(tenths, 1)} MB`
}
