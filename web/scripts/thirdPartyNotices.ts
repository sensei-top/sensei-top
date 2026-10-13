/** The dashboard's third-party notices: every npm package whose code is in
 *  the bundle, with its version, its licence and the licence texts it ships,
 *  then the Mana glyphs, which come from no package. `vite.config.ts`'s
 *  plugin hands this the module ids Rollup put in the bundle and writes the
 *  text to `third-party-notices.txt` at the root of `web_dist`, where the
 *  credits view fetches it (docs/attribution.md, "Software in the installed
 *  app").
 *
 *  Everything here is pure but for `fsPackageReader`, so a test drives it
 *  with a small tree of its own. */

import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

/** How the notices read a package's folder. */
export interface PackageReader {
  /** A file's text, or null when it does not exist. */
  readText(path: string): string | null
  /** The names of the regular files directly inside a folder, or an empty
   *  list when it does not exist. */
  listFiles(dir: string): string[]
}

export const fsPackageReader: PackageReader = {
  readText(path) {
    try {
      return readFileSync(path, 'utf8')
    } catch {
      return null
    }
  },
  listFiles(dir) {
    try {
      return readdirSync(dir, { withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) => entry.name)
    } catch {
      return []
    }
  },
}

export const NOTICES_OPENING = `Third-party notices for the Sensei Top dashboard.

Every work below is built into the dashboard's scripts, styles and
fonts. Each is listed with its version and licence, followed by the
licence text it ships.`

export const MANA_ENTRY = `Mana, by Andrew Gioia — https://github.com/andrewgioia/mana
Glyphs under SIL OFL 1.1. Mana symbol imagery © Wizards of the Coast.
The licence text is the SIL Open Font License 1.1, as reproduced in the
@fontsource-variable entries above.`

export const SEPARATOR = '-'.repeat(72)

export const NO_LICENCE_FILE = '(The package ships no licence file.)'

const LICENCE_FILE = /^(LICENSE|LICENCE|COPYING|NOTICE)/i

/** The folder of the package a module id belongs to: the nearest
 *  `node_modules/<name>` or `node_modules/@scope/<name>` above it, which in
 *  pnpm's `.pnpm/<x>/node_modules/<name>` layout is the real package.
 *  Null for a virtual id (`\0…`), which `buildNotices` maps by its
 *  prefix instead, and for a file outside any `node_modules`, which is the
 *  project's own. */
export function packageDirOf(moduleId: string): string | null {
  if (moduleId.startsWith('\0')) return null
  const path = moduleId.split('?')[0].replaceAll('\\', '/')
  const marker = '/node_modules/'
  const at = path.lastIndexOf(marker)
  if (at < 0) return null
  const rest = path.slice(at + marker.length).split('/')
  const nameParts = rest[0].startsWith('@') ? 2 : 1
  if (rest.length <= nameParts || rest.slice(0, nameParts).some((part) => part === '')) return null
  return path.slice(0, at + marker.length) + rest.slice(0, nameParts).join('/')
}

interface PackageNotice {
  name: string
  version: string
  hasFile: boolean
  text: string
}

export interface NoticesResult {
  text: string
  /** Packages read, each `name version`, in the order they are written. */
  packages: string[]
  /** Packages that ship no licence file and are listed by their field. */
  withoutFile: string[]
  /** Packages that cannot be listed: no package.json, or neither a licence
   *  file nor a `license` field. The build fails on any. */
  errors: string[]
}

/** The licence package.json names, as written: the `license` string, or the
 *  older object and `licenses` list forms by their `type`. */
function licenceField(pkg: Record<string, unknown>): string | null {
  const types = (value: unknown): string[] => {
    if (typeof value === 'string') return [value]
    if (value && typeof value === 'object' && typeof (value as { type?: unknown }).type === 'string') {
      return [(value as { type: string }).type]
    }
    return []
  }
  const named = [
    ...types(pkg.license),
    ...(Array.isArray(pkg.licenses) ? pkg.licenses.flatMap(types) : []),
  ].filter((type) => type.trim() !== '')
  return named.length > 0 ? named.join(' OR ') : null
}

/** The repository package.json names, as an address a browser opens:
 *  `git+` and `.git` dropped, and npm's `owner/repo` and `github:owner/repo`
 *  shorthands spelled out, as npm itself reads them. */
function repositoryUrl(pkg: Record<string, unknown>): string | null {
  const repo = pkg.repository
  const raw =
    typeof repo === 'string'
      ? repo
      : repo && typeof repo === 'object' && typeof (repo as { url?: unknown }).url === 'string'
        ? (repo as { url: string }).url
        : null
  if (!raw || raw.trim() === '') return null
  let url = raw.trim().replace(/^git\+/, '').replace(/\.git$/, '')
  if (url.startsWith('git://')) url = `https://${url.slice('git://'.length)}`
  if (url.startsWith('github:')) url = `https://github.com/${url.slice('github:'.length)}`
  else if (/^[\w.-]+\/[\w.-]+$/.test(url)) url = `https://github.com/${url}`
  return url
}

/** Where to cut a package's licence text: at the first line equal to
 *  `heading`, which is dropped with everything after it. */
export interface LicenceCut {
  heading: string
}

type PackageOptions = Required<Pick<NoticesOptions, 'cuts' | 'extraFiles' | 'extraNotices'>>

/** A text file read as the notices write it: LF line ends, no trailing
 *  blank lines. */
function normalized(text: string): string {
  return text.replace(/\r\n?/g, '\n').trimEnd()
}

function readPackage(
  dir: string,
  reader: PackageReader,
  { cuts, extraFiles, extraNotices }: PackageOptions,
  seen: Set<string>,
): PackageNotice | string {
  const manifest = reader.readText(join(dir, 'package.json'))
  if (manifest === null) return `${dir}: no package.json`
  let pkg: Record<string, unknown>
  try {
    pkg = JSON.parse(manifest) as Record<string, unknown>
  } catch {
    return `${dir}: package.json is not JSON`
  }
  const name = typeof pkg.name === 'string' ? pkg.name : null
  const version = typeof pkg.version === 'string' ? pkg.version : null
  if (!name || !version) return `${dir}: package.json names no name or version`
  seen.add(name)

  const licence = licenceField(pkg)
  const files = reader
    .listFiles(dir)
    .filter((file) => LICENCE_FILE.test(file))
    .sort()
  const named = Object.hasOwn(extraFiles, name) ? extraFiles[name].filter((file) => !files.includes(file)) : []
  const missing = named.filter((file) => reader.readText(join(dir, file)) === null)
  if (missing.length > 0) return `${name} ${version}: no file ${missing.join(', ')}`
  let texts = [...files, ...named]
    .map((file) => reader.readText(join(dir, file)))
    .filter((text): text is string => text !== null)
    .map(normalized)
    .filter((text) => text !== '')
  const cut = Object.hasOwn(cuts, name) ? cuts[name] : undefined
  if (cut) {
    // A file whose shape changed is noticed, not copied whole or emptied.
    if (!texts.some((text) => text.split('\n').includes(cut.heading))) {
      return `${name} ${version}: no licence file has the line "${cut.heading}" to cut it at`
    }
    texts = texts.map((text) => {
      const lines = text.split('\n')
      const at = lines.indexOf(cut.heading)
      return at < 0 ? text : lines.slice(0, at).join('\n').trimEnd()
    })
    texts = texts.filter((text) => text !== '')
  }
  if (licence === null && texts.length === 0) {
    return `${name} ${version}: neither a licence file nor a license field`
  }

  const head = [`${name} ${version}`]
  if (licence !== null) head.push(licence)
  const repo = repositoryUrl(pkg)
  if (repo) head.push(repo)
  const notes: string[] = []
  for (const path of Object.hasOwn(extraNotices, name) ? extraNotices[name] : []) {
    const note = reader.readText(path)
    if (note === null) return `${name} ${version}: no notice file ${path}`
    notes.push(normalized(note))
  }

  const body = texts.length > 0 ? texts.join('\n\n') : NO_LICENCE_FILE
  const text = [`${head.join('\n')}\n\n${body}`, ...notes].join(`\n\n${SEPARATOR}\n\n`)
  return { name, version, hasFile: texts.length > 0, text }
}

export interface NoticesOptions {
  /** Package folders whose code is in the bundle though no module id shows
   *  them. */
  extraDirs?: Iterable<string>
  /** By package name: a licence file that also carries texts for code that
   *  never reaches the bundle is cut where those begin. */
  cuts?: Record<string, LicenceCut>
  /** By package name: files to take beside its licence files, whose names
   *  the pattern does not catch. A named file that is missing is an error. */
  extraFiles?: Record<string, string[]>
  /** By prefix (`\0vite/`): the package folder a virtual module's code comes
   *  from. A virtual id no prefix matches is an error, so code of unknown
   *  origin never ships without a notice. */
  virtualDirs?: Record<string, string>
  /** By package name: paths of notice files written for this project, for
   *  code a package copied from another work whose notice it does not
   *  ship. Each is added to the package's entry after its own licence
   *  texts, behind a line of dashes. A missing file is an error. */
  extraNotices?: Record<string, string[]>
}

/** The notices for the packages the module ids belong to, plus the
 *  `extraDirs`, sorted by name, then the Mana entry. */
export function buildNotices(
  moduleIds: Iterable<string>,
  reader: PackageReader,
  { extraDirs = [], cuts = {}, extraFiles = {}, virtualDirs = {}, extraNotices = {} }: NoticesOptions = {},
): NoticesResult {
  const dirs = new Set<string>()
  const errors: string[] = []
  for (const id of moduleIds) {
    if (id.startsWith('\0')) {
      const prefix = Object.keys(virtualDirs).find((p) => id.startsWith(p))
      if (prefix === undefined) errors.push(`virtual module \\0${id.slice(1)}: no package is known for it`)
      else dirs.add(virtualDirs[prefix].replaceAll('\\', '/'))
      continue
    }
    const dir = packageDirOf(id)
    if (dir) dirs.add(dir)
  }
  for (const dir of extraDirs) dirs.add(dir.replaceAll('\\', '/'))

  const notices: PackageNotice[] = []
  // Every package name found, including those whose entry failed.
  const names = new Set<string>()
  for (const dir of dirs) {
    const read = readPackage(dir, reader, { cuts, extraFiles, extraNotices }, names)
    if (typeof read === 'string') errors.push(read)
    else notices.push(read)
  }
  // A key that names no package would drop its cut, file or notice silently.
  const options = { cuts, extraFiles, extraNotices }
  for (const [option, keyed] of Object.entries(options)) {
    for (const key of Object.keys(keyed)) {
      if (!names.has(key)) errors.push(`${option}: no package in the bundle is named "${key}"`)
    }
  }
  // Two folders of one version (a package linked twice) are one entry.
  const unique = [...new Map(notices.map((n) => [`${n.name}@${n.version}`, n])).values()]
  unique.sort((a, b) => (a.name === b.name ? cmp(a.version, b.version) : cmp(a.name, b.name)))

  const entries = [...unique.map((n) => n.text), MANA_ENTRY]
  return {
    text: `${NOTICES_OPENING}\n\n${entries.join(`\n\n${SEPARATOR}\n\n`)}\n`,
    packages: unique.map((n) => `${n.name} ${n.version}`),
    withoutFile: unique.filter((n) => !n.hasFile).map((n) => `${n.name} ${n.version}`),
    errors: errors.sort(),
  }
}

/** Code-point order, so the file is the same on every machine and locale. */
function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}
