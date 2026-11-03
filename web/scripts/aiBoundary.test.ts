import { spawnSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

// The boundary around src/ai/ is a lint rule, so the test is a lint run:
// the dashboard's own .oxlintrc.json, copied beside a few probe files in a
// temporary folder (its globs are relative to where it sits), and oxlint's
// verdict on each.

const WEB = join(dirname(fileURLToPath(import.meta.url)), '..')
const CONFIG = join(WEB, '.oxlintrc.json')
const OXLINT = join(WEB, 'node_modules', '.bin', 'oxlint')
const RULE = 'no-restricted-imports'

interface Override {
  files: string[]
  rules: Record<string, unknown>
}

/** The files the config lets import ai/ modules directly: those whose
 *  override turns the boundary rule off. */
function exceptions(): string[] {
  const config = JSON.parse(readFileSync(CONFIG, 'utf8')) as { overrides?: Override[] }
  return (config.overrides ?? []).filter((o) => o.rules[RULE] === 'off').flatMap((o) => o.files)
}

let root: string

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), 'ai-boundary-'))
  copyFileSync(CONFIG, join(root, '.oxlintrc.json'))
})

afterEach(() => {
  rmSync(root, { recursive: true, force: true })
})

/** Writes one probe file, `path` relative to the probe's web folder, that
 *  imports `from` and uses it, and returns the boundary rule's findings on it
 *  as oxlint's exit status and its lines naming the rule. */
function lint(path: string, from: string): { status: number | null; findings: string[] } {
  const file = join(root, path)
  mkdirSync(dirname(file), { recursive: true })
  writeFileSync(file, `import { Thing } from '${from}'\nexport const used = Thing\n`)
  const run = spawnSync(OXLINT, ['-c', '.oxlintrc.json', '-f', 'unix', path], { cwd: root, encoding: 'utf8' })
  const findings = run.stdout.split('\n').filter((line) => line.includes(RULE))
  return { status: run.status, findings }
}

describe('the src/ai/ boundary', () => {
  it('fails the lint for an ai/ module imported from outside ai/', () => {
    const result = lint('src/views/Probe.tsx', '../ai/GenerateCard')
    expect(result.findings).toHaveLength(1)
    expect(result.findings[0]).toContain('Error')
    expect(result.status).not.toBe(0)
  })

  it('fails the lint for a module deeper inside ai/', () => {
    const result = lint('src/components/guide/Probe.tsx', '../../ai/coach/Report')
    expect(result.findings).toHaveLength(1)
    expect(result.status).not.toBe(0)
  })

  it('fails the lint for ai/ imported as a folder', () => {
    const result = lint('src/views/Probe.tsx', '../ai')
    expect(result.findings).toHaveLength(1)
    expect(result.status).not.toBe(0)
  })

  it('lets anything import the registry', () => {
    const result = lint('src/views/Probe.tsx', '../ai/registry')
    expect(result.findings).toEqual([])
    expect(result.status).toBe(0)
  })

  it('lets ai/ import its own modules', () => {
    const result = lint('src/ai/Probe.tsx', './CopyPromptCard')
    expect(result.findings).toEqual([])
    expect(result.status).toBe(0)
  })

  it.skipIf(exceptions().length === 0)('lets a named exception import an ai/ module directly', () => {
    const [first] = exceptions()
    const result = lint(first, '../ai/GenerateCard')
    expect(result.findings).toEqual([])
  })
})

describe('the exceptions to the src/ai/ boundary', () => {
  // An exception outlives its need silently: once a file reaches ai/ only
  // through the registry, its line in the config has to go.
  it('names only files that still import an ai/ module other than the registry', () => {
    for (const path of exceptions()) {
      const file = join(WEB, path)
      expect(existsSync(file), path).toBe(true)
      const imports = [...readFileSync(file, 'utf8').matchAll(/from '([^']+)'/g)].map((m) => m[1])
      expect(
        imports.some((from) => /(^|\/)ai(\/(?!registry$)|$)/.test(from)),
        path,
      ).toBe(true)
    }
  })
})
