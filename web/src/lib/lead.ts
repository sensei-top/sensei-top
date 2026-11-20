import { inlineText, parseInline } from './markdown'

const CAP = 200

/** The one line a closed block shows: the stored `lead` when it has words,
 *  else the first sentence of `prose` (a sentence ends at `. `, `? ` or `! `
 *  before an uppercase letter, never inside "e.g.", "i.e." or "vs."). `prose` may
 *  be Markdown: leading heading lines are skipped and emphasis and
 *  citations dropped as `parseInline` reads them. Capped at 200 characters, cut at a word, with an ellipsis. */
export function leadOf(lead: string | null | undefined, prose: string): string {
  const stored = lead?.trim()
  if (stored) return stored
  const lines = prose.split('\n')
  while (lines.length > 0 && (/^\s*#{1,6}(\s|$)/.test(lines[0]) || lines[0].trim() === '')) lines.shift()
  const text = inlineText(parseInline(lines.join(' ')))
  return cap(firstSentence(text))
}

function firstSentence(text: string): string {
  const end = /[.?!] (?=\p{Lu})/gu
  for (let m = end.exec(text); m; m = end.exec(text)) {
    if (m[0] === '. ' && /(?:^|[^A-Za-z])(?:e\.g|i\.e|vs)$/i.test(text.slice(0, m.index))) continue
    return text.slice(0, m.index + 1)
  }
  return text
}

function cap(text: string): string {
  if (text.length <= CAP) return text
  const room = text.slice(0, CAP)
  const space = room.lastIndexOf(' ')
  const cut = space > 0 ? room.slice(0, space) : room.slice(0, CAP - 1)
  return `${cut.replace(/[\s.,;:]+$/, '')}…`
}
