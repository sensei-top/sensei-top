import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

/*
 * The dashboard's translation check (plan 18, D5). oxlint has no rule for a
 * literal string, so this walks `src/` with the TypeScript compiler and
 * fails on text a person reads that is written in the code rather than
 * keyed into a catalogue (`src/locales/en/<namespace>.json`):
 *
 * - a JSX text node with a letter in it;
 * - a string with a letter in it as a JSX child expression
 *   (`{ready ? 'Done' : 'Waiting'}`), through `?:`, `&&`, `||`, `??`, `+`,
 *   parentheses, `as`, `satisfies`, an array's elements and a template's
 *   own text, never into a call (so `t('…')` is never read as text);
 * - the same, as the value of any JSX attribute but the ones that never
 *   hold text (`NOT_TEXT`): `title`, `aria-label`, `placeholder`, `alt`,
 *   `label`, and every component's own text props (`message`, `hint`, …).
 *
 * And it reads every key the code names, `t('shell.places.home')` or
 * `<Trans i18nKey="…">`, against the English catalogues.
 *
 * It also holds the Brazilian Portuguese catalogues to English's: the same
 * namespaces and keys, no orphans, the same tags, and the same placeholders
 * (for a plural form, any its English forms use, plus `count`).
 *
 * What it cannot see: a sentence built in a plain `.ts` file (`lib/*.ts`
 * returning "3 matches"), an object literal's text in a `.tsx` (an option
 * list's `{ label: 'Arena' }`), a string passed through a call or a
 * variable before it reaches JSX, and a key built at run time
 * (`t(`x.${y}`)`). Those are found by reading the file.
 */

/** D9: never keyed. The design reference pages are a developer's
 *  reference, not a page users reach. Always on the list; a `.ts` file
 *  here holds nothing this check can see anyway. */
const NEVER_KEYED: readonly string[] = ['views/DesignView.tsx', 'views/SurfacesView.tsx', 'lib/sampleShell.ts']

/** Not extracted yet, under the phase that extracts them; each phase takes
 *  its own lines out. A path is relative to `src/`; one ending in `/` is a
 *  folder and everything under it. An entry with nothing left to find
 *  fails the check, so a phase cannot forget its lines. */
const NOT_YET_EXTRACTED: readonly string[] = []

/** JSX attributes that never hold text a person reads. Every other
 *  attribute's literal text is a finding. */
const NOT_TEXT: ReadonlySet<string> = new Set([
  'className',
  'i18nKey',
  'key',
  'id',
  'href',
  'to',
  'src',
  'rel',
  'target',
  'type',
  'role',
  'scope',
  'as',
  'variant',
  'tone',
  'size',
  'fade',
  'placement',
  'color',
  'colorClass',
  'dataKey',
  'domain',
  'height',
  'width',
  'interval',
  'autoComplete',
  'loading',
  'layout',
  'position',
  'iconType',
  'fill',
  'transform',
  'd',
  'textAnchor',
  'dominantBaseline',
  'htmlFor',
  'replayHref',
  'matchHref',
  'importCommand',
  'aria-labelledby',
  'aria-describedby',
  'aria-controls',
  'aria-haspopup',
  'aria-current',
  'aria-live',
  'aria-hidden',
])

const WEB = join(import.meta.dirname, '..')
const SRC = join(WEB, 'src')
const LOCALES = join(SRC, 'locales')

/** Every source file a person's text could be in: not a test, not the
 *  generated API types, not a catalogue. Paths relative to `src/`, with
 *  forward slashes. */
function sourceFiles(dir = SRC): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    const rel = relative(SRC, full).split(sep).join('/')
    if (entry.isDirectory()) {
      if (rel !== 'types' && rel !== 'locales') files.push(...sourceFiles(full))
    } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !entry.name.endsWith('.d.ts')) {
      files.push(rel)
    }
  }
  return files.sort()
}

function parse(rel: string): ts.SourceFile {
  const kind = rel.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  return ts.createSourceFile(rel, readFileSync(join(SRC, rel), 'utf8'), ts.ScriptTarget.Latest, true, kind)
}

// An HTML entity (`&nbsp;`, `&middot;`) is not a word.
const hasLetters = (text: string) => /\p{L}/u.test(text.replace(/&[#\w]+;/g, ''))

/** The literal text an expression renders as it is: through `?:`, `&&`,
 *  `||`, `??`, `+`, parentheses, `as` and `satisfies`, an array's elements
 *  (`columns={['Archetype', 'Won']}`) and a template's own parts, never
 *  into a call. */
function literalTexts(node: ts.Expression): string[] {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return [node.text]
  if (ts.isTemplateExpression(node)) return [node.head.text, ...node.templateSpans.map((span) => span.literal.text)]
  if (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isSatisfiesExpression(node)) {
    return literalTexts(node.expression)
  }
  if (ts.isArrayLiteralExpression(node)) {
    return node.elements.flatMap((element) => (ts.isSpreadElement(element) ? literalTexts(element.expression) : literalTexts(element)))
  }
  if (ts.isConditionalExpression(node)) return [...literalTexts(node.whenTrue), ...literalTexts(node.whenFalse)]
  if (ts.isBinaryExpression(node)) {
    const op = node.operatorToken.kind
    if (op === ts.SyntaxKind.AmpersandAmpersandToken) return literalTexts(node.right)
    if (
      op === ts.SyntaxKind.BarBarToken ||
      op === ts.SyntaxKind.QuestionQuestionToken ||
      op === ts.SyntaxKind.PlusToken
    ) {
      return [...literalTexts(node.left), ...literalTexts(node.right)]
    }
  }
  return []
}

type Finding = { file: string; line: number; what: string }

/** Every piece of literal text a person would read in one file. */
function findingsIn(rel: string): Finding[] {
  const source = parse(rel)
  const found: Finding[] = []
  const add = (node: ts.Node, what: string) =>
    found.push({ file: rel, line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, what })

  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node)) {
      const text = node.text.replace(/\s+/g, ' ').trim()
      if (hasLetters(text)) add(node, `text "${text}"`)
    } else if (ts.isJsxExpression(node) && node.expression && !ts.isJsxAttribute(node.parent)) {
      for (const text of literalTexts(node.expression)) if (hasLetters(text)) add(node, `text {"${text}"}`)
    } else if (ts.isJsxAttribute(node) && node.initializer && !NOT_TEXT.has(node.name.getText())) {
      const value = node.initializer
      const texts = ts.isStringLiteral(value)
        ? [value.text]
        : ts.isJsxExpression(value) && value.expression
          ? literalTexts(value.expression)
          : []
      for (const text of texts) if (hasLetters(text)) add(node, `${node.name.getText()}="${text}"`)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return found
}

const listed = (rel: string, entry: string) => (entry.endsWith('/') ? rel.startsWith(entry) : rel === entry)

/** Every key the code names as a literal: `t('…')`, `i18n.t('…')`,
 *  `<Trans i18nKey="…">`. */
function keysIn(rel: string): { key: string; line: number }[] {
  const source = parse(rel)
  const keys: { key: string; line: number }[] = []
  const add = (node: ts.Node, key: string) =>
    keys.push({ key, line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1 })
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node)) {
      const callee = node.expression
      const isT =
        (ts.isIdentifier(callee) && callee.text === 't') ||
        (ts.isPropertyAccessExpression(callee) && callee.name.text === 't')
      const first = node.arguments[0]
      if (isT && first && (ts.isStringLiteral(first) || ts.isNoSubstitutionTemplateLiteral(first))) {
        add(first, first.text)
      }
    } else if (ts.isJsxAttribute(node) && node.name.getText() === 'i18nKey' && node.initializer) {
      if (ts.isStringLiteral(node.initializer)) add(node, node.initializer.text)
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return keys
}

type Catalogue = { [key: string]: string | Catalogue }

/** One language's catalogues, by namespace. */
function cataloguesOf(language: string): Record<string, Catalogue> {
  const catalogues: Record<string, Catalogue> = {}
  for (const name of readdirSync(join(LOCALES, language))) {
    if (name.endsWith('.json')) {
      catalogues[name.slice(0, -'.json'.length)] = JSON.parse(readFileSync(join(LOCALES, language, name), 'utf8'))
    }
  }
  return catalogues
}

/** The English catalogues, by namespace. */
function englishCatalogues(): Record<string, Catalogue> {
  return cataloguesOf('en')
}

/** Every string leaf as its dotted path (namespace first) and its text. */
function stringLeaves(node: unknown, path: string): [string, string][] {
  if (typeof node === 'string') return [[path, node]]
  if (typeof node !== 'object' || node === null || Array.isArray(node)) return []
  return Object.entries(node).flatMap(([key, value]) => stringLeaves(value, `${path}.${key}`))
}

const sorted = (values: Iterable<string>) => [...new Set(values)].sort()
const placeholdersOf = (text: string) => sorted([...text.matchAll(/\{\{\s*([^}\s,]+)[^}]*\}\}/g)].map((m) => m[1]))
const tagsOf = (text: string) => sorted([...text.matchAll(/<\/?([A-Za-z0-9]+)\s*\/?>/g)].map((m) => m[1]))

const PLURALS = ['', '_zero', '_one', '_two', '_few', '_many', '_other']

/** Whether `key` (`shell.places.home`) names a string in the English
 *  catalogues, itself or as a plural's forms (`…_one`, `…_other`). */
function keyExists(catalogues: Record<string, Catalogue>, key: string): boolean {
  const [namespace, ...path] = key.split('.')
  let node: string | Catalogue | undefined = catalogues[namespace]
  for (const part of path.slice(0, -1)) node = typeof node === 'object' ? node[part] : undefined
  const last = path.at(-1)
  if (typeof node !== 'object' || last === undefined) return false
  return PLURALS.some((suffix) => typeof node[last + suffix] === 'string')
}

/** Each leaf that is not a non-empty string, as its dotted path. */
function badLeaves(node: unknown, path: string): string[] {
  if (typeof node === 'string') return node.trim() ? [] : [path]
  if (typeof node !== 'object' || node === null || Array.isArray(node)) return [path]
  return Object.entries(node).flatMap(([key, value]) => badLeaves(value, `${path}.${key}`))
}

// A failure lists what it found, bounded, so a run never floods the output.
function report(lines: string[]): string {
  const shown = lines.slice(0, 60)
  return [...shown, ...(lines.length > shown.length ? [`… and ${lines.length - shown.length} more`] : [])].join('\n')
}

const FILES = sourceFiles()

describe('the dashboard keys every string a person reads', () => {
  const allowed = [...NEVER_KEYED, ...NOT_YET_EXTRACTED]
  const findings = FILES.flatMap(findingsIn)

  it('has no literal text outside the allowlist', () => {
    const outside = findings.filter((f) => !allowed.some((entry) => listed(f.file, entry)))
    expect(report(outside.map((f) => `src/${f.file}:${f.line}  ${f.what}`))).toBe('')
  })

  it('lists nothing on the allowlist that is already extracted, or that is not there', () => {
    const stale = NOT_YET_EXTRACTED.filter((entry) => !findings.some((f) => listed(f.file, entry)))
    const missing = NEVER_KEYED.filter((entry) => !FILES.includes(entry))
    expect([
      ...stale.map((entry) => `${entry}: nothing left to extract; take it off NOT_YET_EXTRACTED`),
      ...missing.map((entry) => `${entry}: no such file`),
    ]).toEqual([])
  })

  // The design reference pages are never keyed, so they always hold text: the
  // check's standing proof that it still finds any, once nothing is left on
  // NOT_YET_EXTRACTED to go stale.
  it('still finds the text on the design reference pages', () => {
    const silent = NEVER_KEYED.filter((entry) => entry.endsWith('.tsx') && !findings.some((f) => f.file === entry))
    expect(silent.map((entry) => `${entry}: no text found; the check has stopped seeing it`)).toEqual([])
  })
})

describe('the catalogues', () => {
  const catalogues = englishCatalogues()

  it('hold only text, nested by key', () => {
    const bad = Object.entries(catalogues).flatMap(([namespace, catalogue]) => badLeaves(catalogue, namespace))
    expect(bad).toEqual([])
  })

  // react-i18next reads a tag's name against HTML's void elements, so
  // `<link>…</link>` becomes an empty element with the words after it.
  it('use no tag named for an HTML void element', () => {
    const VOID = 'area|base|br|col|embed|hr|img|input|link|meta|param|source|track|wbr'
    const tag = new RegExp(`<(${VOID})\\b[^>]*>`, 'gi')
    const leaves = (node: unknown, path: string): [string, string][] =>
      typeof node === 'string'
        ? [[path, node]]
        : typeof node === 'object' && node !== null
          ? Object.entries(node).flatMap(([key, value]) => leaves(value, `${path}.${key}`))
          : []
    const found = Object.entries(catalogues).flatMap(([namespace, catalogue]) =>
      leaves(catalogue, namespace).flatMap(([key, value]) =>
        [...value.matchAll(tag)].map((match) => `${key}  <${match[1]}>`),
      ),
    )
    expect(found).toEqual([])
  })

  it('have every key the code names', () => {
    const missing = FILES.flatMap((rel) =>
      keysIn(rel)
        .filter(({ key }) => !keyExists(catalogues, key))
        .map(({ key, line }) => `src/${rel}:${line}  ${key}`),
    )
    expect(report(missing)).toBe('')
  })
})

describe('the Brazilian Portuguese catalogues', () => {
  const english = englishCatalogues()
  const portuguese = cataloguesOf('pt-BR')

  it('have the same namespaces as English', () => {
    expect(Object.keys(portuguese).sort()).toEqual(Object.keys(english).sort())
  })

  it('have every English key, and no key English lacks', () => {
    const en = new Map(Object.entries(english).flatMap(([ns, c]) => stringLeaves(c, ns)))
    const pt = new Map(Object.entries(portuguese).flatMap(([ns, c]) => stringLeaves(c, ns)))
    const missing = [...en.keys()].filter((key) => !pt.has(key)).map((key) => `${key}  missing in pt-BR`)
    const orphans = [...pt.keys()].filter((key) => !en.has(key)).map((key) => `${key}  has no English key`)
    expect(report(missing)).toBe('')
    expect(report(orphans)).toBe('')
  })

  // Portuguese reads the `one` category at 0 as well as 1, so a pt-BR `_one`
  // may carry `{{count}}` where the English `_one` spells "one". A plural key
  // (a suffixed key with a sibling form) therefore needs only a subset of the placeholders of all the English forms
  // of its stem together, plus `count`; `catalogue_problems` in `src/sensei_top/i18n.py`
  // applies the same subset rule to `.po` plurals. Every other key must match.
  it('keep every placeholder and tag of the English text', () => {
    const enLeaves = Object.entries(english).flatMap(([ns, c]) => stringLeaves(c, ns))
    const pt = new Map(Object.entries(portuguese).flatMap(([ns, c]) => stringLeaves(c, ns)))
    const SUFFIX = /_(zero|one|two|few|many|other)$/
    const differing: string[] = []
    for (const [key, text] of enLeaves) {
      const translated = pt.get(key)
      if (translated === undefined) continue
      const have = placeholdersOf(translated)
      const stem = key.replace(SUFFIX, '')
      const siblings = enLeaves.filter(([k]) => k !== key && k.replace(SUFFIX, '') === stem)
      if (SUFFIX.test(key) && siblings.length > 0) {
        const allowed = new Set(['count', ...[text, ...siblings.map(([, t]) => t)].flatMap(placeholdersOf)])
        const extra = have.filter((name) => !allowed.has(name))
        if (extra.length) differing.push(`${key}  placeholders {{${extra}}} not in any English form`)
      } else if (placeholdersOf(text).join() !== have.join()) {
        differing.push(`${key}  placeholders {{${placeholdersOf(text)}}} vs {{${have}}}`)
      }
      if (tagsOf(text).join() !== tagsOf(translated).join()) {
        differing.push(`${key}  tags <${tagsOf(text)}> vs <${tagsOf(translated)}>`)
      }
    }
    expect(report(differing)).toBe('')
  })

  it('hold only text, nested by key', () => {
    const bad = Object.entries(portuguese).flatMap(([namespace, catalogue]) => badLeaves(catalogue, namespace))
    expect(bad).toEqual([])
  })
})
