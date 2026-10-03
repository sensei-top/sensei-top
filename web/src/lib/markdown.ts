/**
 * The small Markdown a coach report is written in, read into a tree a
 * component draws. Pure: text in, sections out. It knows only what the
 * reports use: `## ` sections, `### ` subheads, paragraphs, `- ` and
 * `1. ` lists, and inline bold, italic, code, links, bare urls and
 * reading-list citations (`[R4]`). Nothing is ever set as HTML, and no
 * Markdown dependency is needed for this much.
 */

/** A run of inline content, as a tree: a citation inside bold is a `cite`
 *  among the `strong`'s children. A link's children hold no `link`,
 *  `url` or `cite`: one link never holds another. */
export type Inline =
  | { kind: 'text'; text: string }
  | { kind: 'strong'; children: Inline[] }
  | { kind: 'em'; children: Inline[] }
  | { kind: 'code'; text: string }
  | { kind: 'link'; url: string; children: Inline[] }
  | { kind: 'url'; url: string }
  | { kind: 'cite'; label: string }

export type Block =
  | { kind: 'subhead'; inline: Inline[] }
  | { kind: 'paragraph'; inline: Inline[] }
  | { kind: 'list'; ordered: false; items: Inline[][] }
  | { kind: 'list'; ordered: true; start: number; items: Inline[][] }

/** One `## ` section: its heading as written (trimmed), `null` for the
 *  text before the first heading. */
export type ReportSection = { title: string | null; blocks: Block[] }

const SECTION_RE = /^##\s+(.+)$/
const SUBHEAD_RE = /^#{3,}\s+(.+)$/
const UNORDERED_RE = /^[-*] (.*)$/
const ORDERED_RE = /^(\d+)\. (.*)$/

type RawBlock =
  | { kind: 'subhead'; text: string }
  | { kind: 'paragraph'; lines: string[] }
  | { kind: 'list'; ordered: boolean; start: number; items: string[] }

/** A list item's marker read off `line`: its kind, its number (1 for an
 *  unordered one) and the text after it; `null` for a line with none. */
function listItem(line: string): { ordered: boolean; number: number; text: string } | null {
  const unordered = UNORDERED_RE.exec(line)
  if (unordered) return { ordered: false, number: 1, text: unordered[1].trim() }
  const ordered = ORDERED_RE.exec(line)
  if (ordered) return { ordered: true, number: Number(ordered[1]), text: ordered[2].trim() }
  return null
}

function toBlock(raw: RawBlock): Block {
  if (raw.kind === 'subhead') return { kind: 'subhead', inline: parseInline(raw.text) }
  if (raw.kind === 'paragraph') return { kind: 'paragraph', inline: parseInline(raw.lines.join(' ')) }
  const items = raw.items.map((item) => parseInline(item))
  return raw.ordered ? { kind: 'list', ordered: true, start: raw.start, items } : { kind: 'list', ordered: false, items }
}

/** The report's sections. A line `## x` starts a section titled x; text
 *  before the first is a section titled `null`, dropped when it has no
 *  block. In a section, a blank line ends a block. A `### x` line (or
 *  deeper) is a subhead. A line that begins `- ` or `* ` is an item of an
 *  unordered list, one that begins `N. ` an item of an ordered list
 *  starting at the first item's N; a change of marker kind starts a new
 *  list, and a line with no marker right after an item continues it,
 *  joined by one space. Any other run of lines is a paragraph, joined by
 *  one space. A marker line after a paragraph's line starts a list
 *  there, and a subhead line is always a block of its own. */
export function parseReport(text: string): ReportSection[] {
  const sections: ReportSection[] = []
  let current: ReportSection = { title: null, blocks: [] }
  let open: RawBlock | null = null

  const close = () => {
    if (open) current.blocks.push(toBlock(open))
    open = null
  }

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    const section = SECTION_RE.exec(line)
    if (section) {
      close()
      sections.push(current)
      current = { title: section[1].trim(), blocks: [] }
      continue
    }
    if (line === '') {
      close()
      continue
    }
    const subhead = SUBHEAD_RE.exec(line)
    if (subhead) {
      close()
      current.blocks.push({ kind: 'subhead', inline: parseInline(subhead[1].trim()) })
      continue
    }
    const item = listItem(line)
    if (item) {
      const block: RawBlock | null = open
      if (block && block.kind === 'list' && block.ordered === item.ordered) {
        block.items.push(item.text)
      } else {
        close()
        open = { kind: 'list', ordered: item.ordered, start: item.number, items: [item.text] }
      }
      continue
    }
    const block: RawBlock | null = open
    if (block && block.kind === 'list') {
      block.items[block.items.length - 1] += ` ${line}`
    } else if (block && block.kind === 'paragraph') {
      block.lines.push(line)
    } else {
      close()
      open = { kind: 'paragraph', lines: [line] }
    }
  }
  close()
  sections.push(current)
  return sections.filter((s) => s.title != null || s.blocks.length > 0)
}

// --- inline --------------------------------------------------------------

/** What ends the span being read: the closing `**` of a strong, the `*` of
 *  an em, the `]` of a link's label. */
type Stop = '**' | '*' | ']'

const CITE_RE = /^\[R(\d+)\]/
// A bare url stops at a space and at a character that is markup here or
// that a url does not carry unescaped: `*`, a backtick, `<`, `>`, `[`, `]`.
const BARE_URL_RE = /^https?:\/\/[^\s*`<>[\]]+/i
const LINK_URL_RE = /^https?:\/\/\S+$/i
const URL_TAIL = '.,;:)'

const isSpace = (ch: string | undefined) => ch == null || /\s/.test(ch)

/** Whether `stop` closes at `i`. A `**` or `*` closes only after a
 *  character that is not a space; a `*` is not the first of a `**`. */
function closesAt(s: string, i: number, stop: Stop): boolean {
  if (stop === ']') return s[i] === ']'
  if (stop === '**') return s.startsWith('**', i) && !isSpace(s[i - 1])
  return s[i] === '*' && s[i + 1] !== '*' && !isSpace(s[i - 1])
}

/** The `(url)` right after a link's `]` at `close`: the url and the index
 *  past its `)`, or `null`. Parentheses inside the url must balance; a
 *  space ends the attempt. */
function linkTarget(s: string, close: number): { url: string; end: number } | null {
  if (s[close + 1] !== '(') return null
  let depth = 0
  for (let j = close + 2; j < s.length; j++) {
    const ch = s[j]
    if (isSpace(ch)) return null
    if (ch === '(') depth++
    else if (ch === ')') {
      if (depth === 0) return { url: s.slice(close + 2, j), end: j + 1 }
      depth--
    }
  }
  return null
}

type Scan = { nodes: Inline[]; end: number; closed: boolean }

/** Reads `s` from `start` until the innermost of `stops` closes (`closed`
 *  true, `end` at the stop) or an outer one does or the text ends
 *  (`closed` false). `failed` remembers an opener that did not close, so
 *  it is read as text from then on and never tried again. `inLabel` is
 *  set inside a link's label, where a citation, a bare url or a bracketed
 *  run stays text (its brackets balanced, so a `]` inside does not end
 *  the label): one link never holds another. */
function scan(s: string, start: number, stops: Stop[], failed: Set<string>, inLabel: boolean): Scan {
  const nodes: Inline[] = []
  let buffer = ''
  // Adjacent text is one node.
  const push = (node: Inline) => {
    const last = nodes[nodes.length - 1]
    if (node.kind === 'text' && last?.kind === 'text') nodes[nodes.length - 1] = { kind: 'text', text: last.text + node.text }
    else nodes.push(node)
  }
  const flush = () => {
    if (buffer) push({ kind: 'text', text: buffer })
    buffer = ''
  }
  const inner = stops[stops.length - 1]

  let i = start
  while (i < s.length) {
    if (inner && closesAt(s, i, inner)) {
      flush()
      return { nodes, end: i, closed: true }
    }
    if (stops.slice(0, -1).some((stop) => closesAt(s, i, stop))) {
      flush()
      return { nodes, end: i, closed: false }
    }

    const ch = s[i]

    if (ch === '`') {
      const close = s.indexOf('`', i + 1)
      if (close > i + 1) {
        flush()
        nodes.push({ kind: 'code', text: s.slice(i + 1, close) })
        i = close + 1
        continue
      }
      buffer += ch
      i++
      continue
    }

    if (s.startsWith('**', i)) {
      const key = `**@${i}`
      if (!failed.has(key) && !isSpace(s[i + 2])) {
        const body = scan(s, i + 2, [...stops, '**'], failed, inLabel)
        if (body.closed && body.nodes.length > 0) {
          flush()
          nodes.push({ kind: 'strong', children: body.nodes })
          i = body.end + 2
          continue
        }
      }
      failed.add(key)
      buffer += '**'
      i += 2
      continue
    }

    if (ch === '*') {
      const key = `*@${i}`
      if (!failed.has(key) && !isSpace(s[i + 1])) {
        const body = scan(s, i + 1, [...stops, '*'], failed, inLabel)
        if (body.closed && body.nodes.length > 0) {
          flush()
          nodes.push({ kind: 'em', children: body.nodes })
          i = body.end + 1
          continue
        }
      }
      failed.add(key)
      buffer += ch
      i++
      continue
    }

    if (ch === '[' && inLabel) {
      const cite = CITE_RE.exec(s.slice(i))
      if (cite) {
        buffer += cite[0]
        i += cite[0].length
        continue
      }
      const key = `[@${i}`
      if (!failed.has(key)) {
        const bracketed = scan(s, i + 1, [...stops, ']'], failed, true)
        if (bracketed.closed) {
          buffer += '['
          flush()
          for (const node of bracketed.nodes) push(node)
          buffer += ']'
          i = bracketed.end + 1
          continue
        }
      }
      failed.add(key)
      buffer += ch
      i++
      continue
    }

    if (ch === '[') {
      const cite = CITE_RE.exec(s.slice(i))
      // `[R4](https://…)` is a link labelled R4, not a citation.
      if (cite && s[i + cite[0].length] !== '(') {
        flush()
        nodes.push({ kind: 'cite', label: `R${cite[1]}` })
        i += cite[0].length
        continue
      }
      const key = `[@${i}`
      if (!failed.has(key)) {
        const label = scan(s, i + 1, [...stops, ']'], failed, true)
        const target = label.closed ? linkTarget(s, label.end) : null
        if (target && LINK_URL_RE.test(target.url) && label.nodes.length > 0) {
          flush()
          nodes.push({ kind: 'link', url: target.url, children: label.nodes })
          i = target.end
          continue
        }
      }
      failed.add(key)
      if (cite) {
        flush()
        nodes.push({ kind: 'cite', label: `R${cite[1]}` })
        i += cite[0].length
        continue
      }
      buffer += ch
      i++
      continue
    }

    if (!inLabel && (ch === 'h' || ch === 'H')) {
      const bare = BARE_URL_RE.exec(s.slice(i))
      if (bare) {
        let url = bare[0]
        while (url.length > 0 && URL_TAIL.includes(url[url.length - 1])) url = url.slice(0, -1)
        // Past the scheme, something must be left.
        if (/^https?:\/\/./i.test(url)) {
          flush()
          nodes.push({ kind: 'url', url })
          i += url.length
          continue
        }
      }
    }

    buffer += ch
    i++
  }
  flush()
  return { nodes, end: s.length, closed: stops.length === 0 }
}

/** A line's inline content, as a tree: `text`; `strong` (`**…**`) and
 *  `em` (`*…*`), each with children, the opening marker not followed by
 *  a space and the closing one not preceded by one; `code`
 *  (`` `…` ``); `link` (`[label](url)`, only for an `http:`/`https:`
 *  url, parentheses inside it balanced), with children that hold no
 *  `link`, `url` or `cite` (those characters stay text); `url`, a bare
 *  `http(s)://` run, not ending in any of `.,;:)`; `cite`, `[R` digits
 *  `]`, labelled `R4`, unless a `(url)` follows it, which makes it a
 *  link's label. A marker that does not close stays text, and `_` is
 *  never emphasis. */
export function parseInline(text: string): Inline[] {
  return scan(text, 0, [], new Set(), false).nodes
}
