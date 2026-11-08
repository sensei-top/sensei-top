// Text scrubbing in the shell: `src/sensei_top/scrub.py` ported rule for
// rule, so an error report from main carries what one from the local API
// carries. Both pass `tests/fixtures/scrub_vectors.json`: a rule changes in
// both places or in neither.
//
// Traps and contracts:
// - Order matters, as in `scrub.py`: the home directory first (the pattern
//   is `log.ts`'s `homePattern`, the same rule as `logs.py`'s), then the
//   profile folders, emails, tokens, Arena IDs, the legacy MTGO warnings,
//   names last.
// - Python's `\w`, `\b` and `\d` on a str pattern are Unicode; JavaScript's
//   are ASCII. Every one is written out as `WORD`/`DIGIT` under the `u`
//   flag, and every `\b` here precedes a word character, so it is the
//   look-behind `(?<!WORD)`.
// - Python's `casefold` is full case folding; `casefold` below is upper
//   then lower case (ß matches SS), with the final sigma folded too.
// - A `#NNNNN` suffix counts only `\p{Nd}` digits; Python's `isdigit()`
//   also takes superscript and other non-Nd digits, which this port does not.
// - Lines for the legacy MTGO warnings split where Python's `splitlines`
//   splits, terminators kept.
//
// Electron-free: vitest imports it directly.

import * as os from 'node:os';
import { homeAsTilde, homePattern } from '../log';

export const MASK = '<masked>';
export const MIN_NAME = 3;

const WORD = String.raw`[\p{L}\p{N}_]`;
const DIGIT = String.raw`\p{Nd}`;
const NOT_AFTER_WORD = `(?<!${WORD})`;

const SEP = String.raw`(?:\\\\|\\|/)`;
const FOLDER_WORD = String.raw`[^\\/\s"'<>|:*?]+`;
const FOLDER = String.raw`(?:${FOLDER_WORD}(?: ${FOLDER_WORD})*(?=[\\/])|${FOLDER_WORD})`;

const PROFILE_PATHS: readonly RegExp[] = [
  new RegExp(
    String.raw`(${NOT_AFTER_WORD}[A-Z]:${SEP}(?:Users|home|Documents and Settings)${SEP})${FOLDER}`,
    'giu',
  ),
  new RegExp(String.raw`(\\\\+[^\\/\s]+${SEP}Users${SEP})${FOLDER}`, 'giu'),
  new RegExp(String.raw`(?<![\p{L}\p{N}_.])(/(?:run/)?media/)${FOLDER}`, 'gu'),
];
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/gu;
const JWT = new RegExp(String.raw`${NOT_AFTER_WORD}eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*`, 'gu');
const BEARER = new RegExp(String.raw`${NOT_AFTER_WORD}(Bearer\s+)[A-Za-z0-9._~+/=-]+`, 'giu');
const PREFIXED_KEY = new RegExp(
  String.raw`${NOT_AFTER_WORD}(?:sk-ant-|sk-|ghp_|gho_|xox[bap]-|AKIA)[A-Za-z0-9_-]{8,}`,
  'gu',
);
const KEY_VALUE = new RegExp(
  String.raw`${NOT_AFTER_WORD}((?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password)` +
    String.raw`["']?\s*[=:]\s*["']?)[^\s"',;&}]+`,
  'giu',
);
// An Arena user ID: 26 upper-case letters and digits, at least one of each.
const ARENA_ID_BODY = '(?<![A-Za-z0-9])(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*[0-9])[A-Z0-9]{26}(?![A-Za-z0-9])';
const ARENA_ID = new RegExp(ARENA_ID_BODY, 'gu');
const ARENA_ID_WHOLE = new RegExp(`^(?:${ARENA_ID_BODY})$`, 'u');

// `scrub.py`'s `_LEGACY_MTGO`: the MTGO warnings 0.7.0 and earlier wrote with
// a player's handle in them.
const LEGACY_MTGO: ReadonlyArray<readonly [RegExp, string]> = [
  [/(card event handle ).*?( matches neither )/gu, `$1${MASK}$2`],
  [
    /(configured handle ).*?( does not resolve to exactly one opponent among )[^\r\n]*?( for match )/gu,
    `$1${MASK}$2${MASK}$3`,
  ],
  [/(unrecognised (?:mulligan count|hand size) in )[^\r\n]*/gu, `$1${MASK}`],
  [
    new RegExp(
      String.raw`(mulligan count mismatch for ).*?` +
        String.raw`(: 'mulligans to' implied ${DIGIT}+, 'begins the game' implied ${DIGIT}+ )[^\r\n]*`,
      'gu',
    ),
    `$1${MASK}$2(${MASK})`,
  ],
  [/(no preceding start block )\(['"][^\r\n]*/gu, `$1(${MASK})`],
  [/(card event before any game started: )['"][^\r\n]*/gu, `$1${MASK}`],
];

// After each of the terminators Python's `str.splitlines` splits on.
const LINE_END = /(?<=\r\n|\r(?!\n)|[\n\v\f\x1c\x1d\x1e\x85\u2028\u2029])/u;

/** `text` with the player names the legacy MTGO warnings carry masked, line
 *  by line, only on lines that carry `[mtgo]`. */
export function maskLegacyText(text: string): string {
  if (!text.includes('[mtgo]')) return text;
  return text
    .split(LINE_END)
    .map((line) => {
      if (!line.includes('[mtgo]')) return line;
      for (const [pattern, replacement] of LEGACY_MTGO) line = line.replace(pattern, replacement);
      return line;
    })
    .join('');
}

function casefold(text: string): string {
  return text.toUpperCase().toLowerCase().replace(/ς/gu, 'σ');
}

function escapeRegExp(text: string): string {
  // Only the syntax characters: under the `u` flag any other escape is an error.
  return text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
}

const SINGLE_WORD = new RegExp(`^${WORD}+(?:#${DIGIT}+)?$`, 'u');
const ALL_DIGITS = new RegExp(`^${DIGIT}+$`, 'u');
const MARKER = '<(?:user|email|token|id|name|masked)>';
const TOKEN = new RegExp(`${MARKER}|${WORD}+(?:#${DIGIT}+)?`, 'gu');

function expand(names: Iterable<string>): { words: Set<string>; others: string[] } {
  const words = new Set<string>();
  const others = new Set<string>();
  for (const raw of names) {
    const name = raw.trim();
    const candidates = [name];
    const at = name.indexOf('#');
    if (at > 0 && ALL_DIGITS.test(name.slice(at + 1))) candidates.push(name.slice(0, at).trim());
    for (const cand of candidates) {
      if ([...cand].length < MIN_NAME || ARENA_ID_WHOLE.test(cand)) continue;
      if (SINGLE_WORD.test(cand)) words.add(casefold(cand));
      else others.add(cand);
    }
  }
  return { words, others: [...others].sort((a, b) => [...b].length - [...a].length) };
}

function replaceNames(text: string, names: Iterable<string>): string {
  const { words, others } = expand(names);
  if (others.length > 0) {
    const pattern = new RegExp(`(?<!${WORD})(?:${others.map(escapeRegExp).join('|')})(?!${WORD})`, 'giu');
    text = text.replace(pattern, '<name>');
  }
  if (words.size === 0) return text;
  return text.replace(TOKEN, (tok) => {
    if (tok.startsWith('<')) return tok;
    if (words.has(casefold(tok))) return '<name>';
    const at = tok.indexOf('#');
    if (at >= 0 && words.has(casefold(tok.slice(0, at)))) return '<name>' + tok.slice(at);
    return tok;
  });
}

let systemHome: RegExp | null | undefined;

/** This machine's home directory as `homePattern` writes it, worked out once. */
export function defaultHome(): RegExp | null {
  if (systemHome === undefined) systemHome = homePattern(os.homedir(), process.platform === 'win32');
  return systemHome;
}

/** `text` with every identifier it may carry replaced by a marker: the home
 *  directory (`home`, a `homePattern`) by `~`, a profile folder by `<user>`,
 *  emails by `<email>`, tokens and keys by `<token>`, Arena user IDs by
 *  `<id>`, the legacy MTGO warnings' names by `<masked>` and every entry of
 *  `names` by `<name>`. */
export function scrubText(text: string, names: Iterable<string> = [], home: RegExp | null = defaultHome()): string {
  text = homeAsTilde(text, home);
  for (const pattern of PROFILE_PATHS) text = text.replace(pattern, '$1<user>');
  text = text.replace(EMAIL, '<email>');
  text = text.replace(JWT, '<token>');
  text = text.replace(BEARER, '$1<token>');
  text = text.replace(PREFIXED_KEY, '<token>');
  text = text.replace(KEY_VALUE, '$1<token>');
  text = text.replace(ARENA_ID, '<id>');
  text = maskLegacyText(text);
  return replaceNames(text, names);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object') return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/** `value` with every string in it, at any depth of arrays and plain
 *  objects, through `scrubText`. Keys are left alone, as is every key listed
 *  in `skip` and every other kind of value; a cycle comes back as the string
 *  `[Circular]`. */
export function scrubDeep(
  value: unknown,
  names: readonly string[],
  home: RegExp | null = defaultHome(),
  skip: ReadonlySet<string> = new Set(),
): unknown {
  const seen = new WeakSet<object>();
  const walk = (item: unknown): unknown => {
    if (typeof item === 'string') return scrubText(item, names, home);
    if (Array.isArray(item)) {
      if (seen.has(item)) return '[Circular]';
      seen.add(item);
      return item.map(walk);
    }
    if (isPlainObject(item)) {
      if (seen.has(item)) return '[Circular]';
      seen.add(item);
      const out: Record<string, unknown> = {};
      for (const [key, inner] of Object.entries(item)) out[key] = skip.has(key) ? inner : walk(inner);
      return out;
    }
    return item;
  };
  return walk(value);
}
