import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SCRIPT = join(__dirname, 'build-config.mjs')

/** Runs the script with only PATH and the given Supabase URL set. Each case
 *  here is refused before the script writes anything, so the real
 *  build-config.ts is never touched. */
function run(url: string, variable = 'SENSEI_TOP_SUPABASE_URL') {
  return spawnSync(process.execPath, [SCRIPT], {
    env: { PATH: process.env.PATH ?? '', [variable]: url },
    encoding: 'utf8',
  })
}

describe('build-config.mjs', () => {
  it.each([
    ['a path', 'https://example.supabase.co/rest/v1/'],
    ['a query', 'https://example.supabase.co/?x=1'],
    ['a fragment', 'https://example.supabase.co/#top'],
    ['another scheme', 'ftp://example.supabase.co'],
    ['no URL at all', 'example.supabase.co'],
  ])('refuses a Supabase URL with %s, naming the variable but not the value', (_, url) => {
    const result = run(url)
    expect(result.status).toBe(1)
    expect(result.stderr).toContain('SENSEI_TOP_SUPABASE_URL')
    expect(result.stderr).not.toContain('example')
    expect(result.stdout).toBe('')
  })

  it.each([
    ['http', 'http://coach.example.org'],
    ['no URL at all', 'coach.example.org'],
  ])('refuses a coach URL that is %s, naming the variable but not the value', (_, url) => {
    const result = run(url, 'SENSEI_TOP_COACH_URL')
    expect(result.status).toBe(1)
    expect(result.stderr).toContain('SENSEI_TOP_COACH_URL')
    expect(result.stderr).not.toContain('example')
    expect(result.stdout).toBe('')
  })

  it('treats an empty or blank coach URL as unset: no failure, nothing written for it', () => {
    const dir = mkdtempSync(join(tmpdir(), 'build-config-'))
    const out = join(dir, 'build-config.ts')
    try {
      for (const value of ['', '   ']) {
        const result = spawnSync(process.execPath, [SCRIPT], {
          env: { PATH: process.env.PATH ?? '', SENSEI_TOP_COACH_URL: value, SENSEI_TOP_BUILD_CONFIG_OUT: out },
          encoding: 'utf8',
        })
        expect(result.status).toBe(0)
        expect(result.stdout).toContain('no cloud variables')
        expect(readFileSync(out, 'utf8')).not.toContain('coachUrl:')
      }
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })
})
