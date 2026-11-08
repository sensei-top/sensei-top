import { spawnSync } from 'node:child_process'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SCRIPT = join(__dirname, 'build-config.mjs')

/** Runs the script with only PATH and the given Supabase URL set. Each case
 *  here is refused before the script writes anything, so the real
 *  build-config.ts is never touched. */
function run(url: string) {
  return spawnSync(process.execPath, [SCRIPT], {
    env: { PATH: process.env.PATH ?? '', SENSEI_TOP_SUPABASE_URL: url },
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
})
