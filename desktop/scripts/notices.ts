/** The desktop app's third-party notices: every npm package in the shell's
 *  production dependencies (electron-updater and what it pulls in), which
 *  ship inside app.asar bar a few optional ones, with its version, its
 *  licence and the licence texts it ships. `pnpm licenses list --prod
 *  --json` names the packages and their folders; the text lands in
 *  `dist/notices/`, which electron-builder copies to `resources/licenses/`
 *  (docs/attribution.md, "Software in the installed app"). Run by Node's
 *  type stripping: `node scripts/notices.ts`, after `build`, which empties
 *  `dist/`.
 *
 *  Everything here is pure but for `fsReader` and `main`, so a test drives
 *  it with a small tree of its own, the way
 *  web/scripts/thirdPartyNotices.ts is driven. */

import { execFileSync } from 'node:child_process'
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

/** How the notices read a package's folder. */
export interface PackageReader {
  /** A file's text, or null when it does not exist. */
  readText(path: string): string | null
  /** The names of the regular files directly inside a folder, or an empty
   *  list when it does not exist. */
  listFiles(dir: string): string[]
}

export const fsReader: PackageReader = {
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

export const NOTICES_OPENING = `Third-party notices for the Sensei Top desktop app.

Every package below is a production dependency of the desktop app's
window process. A few are optional and may be left out of the build.
Each is listed with its version and licence, followed by the licence
text it ships.`

export const SEPARATOR = '-'.repeat(72)

export const NO_LICENCE_FILE = '(The package ships no licence file.)'

const LICENCE_FILE = /^(LICENSE|LICENCE|COPYING|NOTICE)/i

/** One package, as `pnpm licenses list --prod --json` names it. */
export interface ListedPackage {
  name: string
  version: string
  license: string
  dir: string
}

export interface NoticesResult {
  text: string
  /** Packages written, each `name version`, in the order they are written. */
  packages: string[]
  /** Packages that ship no licence file and are listed by their licence
   *  field alone. The script says so; the build does not stop. */
  withoutFile: string[]
  /** Packages that cannot be listed: no package.json in their folder, or
   *  neither a licence file nor a licence field. The build fails on any. */
  errors: string[]
}

/** Code-point order, so the file is the same on every machine and locale. */
function cmp(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

/** A text file read as the notices write it: LF line ends, no trailing
 *  blank lines. */
function normalized(text: string): string {
  return text.replace(/\r\n?/g, '\n').trimEnd()
}

/** The notices for the packages, sorted by name, then version. */
export function buildNotices(packages: ListedPackage[], reader: PackageReader): NoticesResult {
  const errors: string[] = []
  const withoutFile: string[] = []
  const sorted = [...packages].sort((a, b) =>
    a.name === b.name ? cmp(a.version, b.version) : cmp(a.name, b.name),
  )
  const entries: string[] = []
  const written: string[] = []
  for (const pkg of sorted) {
    const label = `${pkg.name} ${pkg.version}`
    // A wrong layout would otherwise list every package with no text.
    if (reader.readText(join(pkg.dir, 'package.json')) === null) {
      errors.push(`${label}: no package.json in ${pkg.dir}`)
      continue
    }
    const texts = reader
      .listFiles(pkg.dir)
      .filter((file) => LICENCE_FILE.test(file))
      .sort(cmp)
      .map((file) => reader.readText(join(pkg.dir, file)))
      .filter((text): text is string => text !== null)
      .map(normalized)
      .filter((text) => text !== '')
    const licence = pkg.license.trim()
    // pnpm never reports an empty licence: a package with no licence field
    // comes out keyed "Unknown".
    if (texts.length === 0 && (licence === '' || licence === 'Unknown')) {
      errors.push(`${label}: neither a licence file nor a licence field`)
      continue
    }
    if (texts.length === 0) withoutFile.push(label)
    const head = [label]
    if (licence !== '') head.push(licence)
    const body = texts.length > 0 ? texts.join('\n\n') : NO_LICENCE_FILE
    entries.push(`${head.join('\n')}\n\n${body}`)
    written.push(label)
  }
  return {
    text: `${NOTICES_OPENING}\n\n${entries.join(`\n\n${SEPARATOR}\n\n`)}\n`,
    packages: written,
    withoutFile,
    errors: errors.sort(),
  }
}

/** The packages in the JSON `pnpm licenses list --prod --json` prints: an
 *  object from licence to packages, each with its versions and folders. */
export function parseLicenseList(json: string): ListedPackage[] {
  const parsed = JSON.parse(json) as Record<
    string,
    { name: string; versions: string[]; paths: string[] }[]
  >
  const out: ListedPackage[] = []
  for (const [license, list] of Object.entries(parsed)) {
    for (const entry of list) {
      entry.paths.forEach((dir, i) => {
        out.push({ name: entry.name, version: entry.versions[i] ?? entry.versions[0] ?? '', license, dir })
      })
    }
  }
  return out
}

function main(script: string): void {
  const root = resolve(dirname(script), '..')
  const json = execFileSync('pnpm', ['licenses', 'list', '--prod', '--json'], {
    cwd: root,
    encoding: 'utf8',
    shell: process.platform === 'win32',
  })
  const result = buildNotices(parseLicenseList(json), fsReader)
  if (result.errors.length > 0) {
    console.error(`notices: cannot list ${result.errors.length} package(s):\n  ${result.errors.join('\n  ')}`)
    process.exit(1)
  }
  for (const label of result.withoutFile) {
    console.warn(`notices: ${label} ships no licence file; listed by its licence field`)
  }
  const out = join(root, 'dist', 'notices', 'third-party-notices.txt')
  mkdirSync(dirname(out), { recursive: true })
  writeFileSync(out, result.text)
  console.log(`notices: ${result.packages.length} packages written to ${out}`)
}

// Only when node runs this file, not when a test imports it. Not
// `import.meta.url`: tsc checks this file as CommonJS (TS1470).
const script = process.argv[1] ? resolve(process.argv[1]) : ''
if (/[\\/]notices\.ts$/.test(script)) main(script)
