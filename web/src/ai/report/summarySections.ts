import { leadOf } from '../../lib/lead'

/** The match summary's four parts, in the order they are read. */
export const SUMMARY_PARTS = ['games', 'key_leak', 'counter_argument', 'confidence'] as const

export type SummaryPartKey = (typeof SUMMARY_PARTS)[number]

export type SummarySectionsInput = Partial<Record<SummaryPartKey, string | null>> | null | undefined

/** What the card draws: the stored parts, each with words, or the single
 *  paragraph of an older narrative (`sections` null). A parts object with
 *  no words in any part reads as the paragraph too. */
export type SummaryBody =
  | { kind: 'sections'; parts: { key: SummaryPartKey; text: string }[] }
  | { kind: 'prose'; text: string }

export function summaryBody(sections: SummarySectionsInput, prose: string): SummaryBody {
  const parts = SUMMARY_PARTS.flatMap((key) => {
    const text = sections?.[key]?.trim()
    return text ? [{ key, text }] : []
  })
  return parts.length > 0 ? { kind: 'sections', parts } : { kind: 'prose', text: prose }
}

/** The one line that stands for a written summary: the key leak's first
 *  sentence, or null when there is no key leak to quote. */
export function summaryTeaser(sections: SummarySectionsInput): string | null {
  const leak = sections?.key_leak?.trim()
  return leak ? leadOf(null, leak) : null
}
