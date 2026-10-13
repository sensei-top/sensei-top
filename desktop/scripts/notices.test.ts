import { describe, expect, it } from 'vitest'
import {
  buildNotices,
  NO_LICENCE_FILE,
  NOTICES_OPENING,
  parseLicenseList,
  SEPARATOR,
  type PackageReader,
} from './notices'

/** A reader over a small tree: folder to file name to text. */
function treeReader(tree: Record<string, Record<string, string>>): PackageReader {
  return {
    listFiles: (dir) => Object.keys(tree[dir] ?? {}),
    readText: (path) => {
      const parts = path.split(/[\\/]/)
      return tree[parts.slice(0, -1).join('/')]?.[parts[parts.length - 1] ?? ''] ?? null
    },
  }
}

describe('buildNotices', () => {
  it('opens with the notices opening and lists packages sorted by name', () => {
    const reader = treeReader({
      '/p/zed': { 'package.json': '{}', LICENSE: 'Zed text\r\n\r\n' },
      '/p/alpha': { 'package.json': '{}', 'license.md': 'Alpha text', 'README.md': 'not a licence' },
    })
    const result = buildNotices(
      [
        { name: 'zed', version: '1.0.0', license: 'ISC', dir: '/p/zed' },
        { name: 'alpha', version: '2.0.0', license: 'MIT', dir: '/p/alpha' },
      ],
      reader,
    )
    expect(result.errors).toEqual([])
    expect(result.packages).toEqual(['alpha 2.0.0', 'zed 1.0.0'])
    expect(result.text).toBe(
      `${NOTICES_OPENING}\n\nalpha 2.0.0\nMIT\n\nAlpha text\n\n${SEPARATOR}\n\nzed 1.0.0\nISC\n\nZed text\n`,
    )
  })

  it('takes every licence file a package ships', () => {
    const reader = treeReader({ '/p/a': { 'package.json': '{}', LICENSE: 'One', NOTICE: 'Two', 'index.js': 'x' } })
    const result = buildNotices([{ name: 'a', version: '1.0.0', license: 'MIT', dir: '/p/a' }], reader)
    expect(result.text).toContain('One\n\nTwo')
  })

  it('lists a package with no file by its field and reports it', () => {
    const result = buildNotices(
      [{ name: 'a', version: '1.0.0', license: 'MIT', dir: '/p/a' }],
      treeReader({ '/p/a': { 'package.json': '{}' } }),
    )
    expect(result.errors).toEqual([])
    expect(result.withoutFile).toEqual(['a 1.0.0'])
    expect(result.text).toContain(`a 1.0.0\nMIT\n\n${NO_LICENCE_FILE}`)
  })

  it('fails a package with neither a file nor a licence field', () => {
    const result = buildNotices(
      [{ name: 'a', version: '1.0.0', license: 'Unknown', dir: '/p/a' }],
      treeReader({ '/p/a': { 'package.json': '{}' } }),
    )
    expect(result.errors).toEqual(['a 1.0.0: neither a licence file nor a licence field'])
    expect(result.packages).toEqual([])
  })

  it('fails a package whose folder has no package.json', () => {
    const result = buildNotices(
      [{ name: 'a', version: '1.0.0', license: 'MIT', dir: '/p/a' }],
      treeReader({}),
    )
    expect(result.errors).toEqual(['a 1.0.0: no package.json in /p/a'])
    expect(result.packages).toEqual([])
  })
})

describe('parseLicenseList', () => {
  it('flattens the licence-keyed JSON into one package per folder', () => {
    const json = JSON.stringify({
      MIT: [{ name: 'a', versions: ['1.0.0'], paths: ['/p/a'] }],
      ISC: [{ name: 'b', versions: ['2.0.0', '3.0.0'], paths: ['/p/b2', '/p/b3'] }],
    })
    expect(parseLicenseList(json)).toEqual([
      { name: 'a', version: '1.0.0', license: 'MIT', dir: '/p/a' },
      { name: 'b', version: '2.0.0', license: 'ISC', dir: '/p/b2' },
      { name: 'b', version: '3.0.0', license: 'ISC', dir: '/p/b3' },
    ])
  })
})
