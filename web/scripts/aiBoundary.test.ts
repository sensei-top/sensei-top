import { spawnSync } from 'node:child_process'
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
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

function severity(setting: unknown): unknown {
  const level = Array.isArray(setting) ? setting[0] : setting
  return level === 'error' || level === 2 ? 'error' : level
}

/** The files the config lets import ai/ modules directly: those whose
 *  override sets the boundary rule to anything but an error, in either
 *  the plain or the array form. */
function exceptions(): string[] {
  const config = JSON.parse(readFileSync(CONFIG, 'utf8')) as { overrides?: Override[] }
  return (config.overrides ?? []).filter((o) => RULE in o.rules && severity(o.rules[RULE]) !== 'error').flatMap((o) => o.files)
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
})

describe('the exceptions to the src/ai/ boundary', () => {
  // The list is empty: every file outside ai/ reaches it through the
  // registry. A new exception is a design change, not a patch.
  it('names no file', () => {
    expect(exceptions()).toEqual([])
  })
})
