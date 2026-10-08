import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import {
  MANA_ENTRY,
  NOTICES_OPENING,
  NO_LICENCE_FILE,
  SEPARATOR,
  buildNotices,
  fsPackageReader,
  packageDirOf,
} from './thirdPartyNotices.ts'

// A small pnpm-shaped tree, written under the test's own temp dir: no real
// node_modules is read. Each package's folder is the real one under
// `.pnpm/<x>/node_modules/<name>`, as Rollup's ids name it.
let root: string
const pnpm = (store: string, name: string) => `${root}/node_modules/.pnpm/${store}/node_modules/${name}`

function write(path: string, text: string) {
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, text)
}

beforeAll(() => {
  root = mkdtempSync(join(tmpdir(), 'notices-'))

  // A package with a licence file, a repository in npm's object form, and a
  // nested package.json (an `esm/` folder's {"type": "module"}) that is not
  // the package.
  const alpha = pnpm('alpha@1.0.0', 'alpha')
  write(
    `${alpha}/package.json`,
    JSON.stringify({ name: 'alpha', version: '1.0.0', license: 'MIT', repository: { type: 'git', url: 'git+https://github.com/example/alpha.git' } }),
  )
  write(`${alpha}/LICENSE`, 'MIT License\r\n\r\nCopyright (c) Alpha authors\r\n')
  write(`${alpha}/index.js`, '')
  write(`${alpha}/esm/package.json`, JSON.stringify({ type: 'module' }))
  write(`${alpha}/esm/index.js`, '')

  // A scoped package with the field and no file, and the shorthand
  // repository form.
  const beta = pnpm('@scope+beta@2.0.0', '@scope/beta')
  write(`${beta}/package.json`, JSON.stringify({ name: '@scope/beta', version: '2.0.0', license: 'ISC', repository: 'example/beta' }))
  write(`${beta}/dist/beta.js`, '')

  // Files and no field: two licence files, read in name order, and a
  // folder named like one, which is not a file.
  const gamma = pnpm('gamma@3.1.0', 'gamma')
  write(`${gamma}/package.json`, JSON.stringify({ name: 'gamma', version: '3.1.0' }))
  write(`${gamma}/NOTICE`, 'Gamma notice\n')
  write(`${gamma}/LICENSE.md`, 'Gamma licence\n')
  mkdirSync(`${gamma}/LICENSES`, { recursive: true })
  write(`${gamma}/lib/gamma.js`, '')

  // Neither a licence file nor a field.
  const delta = pnpm('delta@0.1.0', 'delta')
  write(`${delta}/package.json`, JSON.stringify({ name: 'delta', version: '0.1.0' }))
  write(`${delta}/index.js`, '')

  // A package found only as an extra folder, the way Tailwind is.
  const epsilon = pnpm('epsilon@4.0.0', 'epsilon')
  write(`${epsilon}/package.json`, JSON.stringify({ name: 'epsilon', version: '4.0.0', license: 'MIT' }))
  write(`${epsilon}/LICENSE`, 'Epsilon licence')

  // A licence file the pattern catches, and one it does not, named for the
  // package the way Rolldown's THIRD-PARTY-LICENSE is.
  const theta = pnpm('theta@6.0.0', 'theta')
  write(`${theta}/package.json`, JSON.stringify({ name: 'theta', version: '6.0.0', license: 'MIT' }))
  write(`${theta}/LICENSE`, 'Theta licence\n')
  write(`${theta}/THIRD-PARTY-LICENSE`, 'Upstream licence\n')

  // A package that copied code from another work, and the notice for it,
  // kept outside any package the way scripts/notices/ is.
  const iota = pnpm('iota@7.0.0', 'iota')
  write(`${iota}/package.json`, JSON.stringify({ name: 'iota', version: '7.0.0', license: 'ISC' }))
  write(`${iota}/LICENSE`, 'Iota licence\n')
  write(`${root}/notices/iota-copied.txt`, 'iota copies part of Kappa, under:\n\nKappa licence\n')

  // A licence file that goes on to carry texts for code bundled into the
  // package itself, the way Vite's LICENSE.md does.
  const eta = pnpm('eta@5.0.0', 'eta')
  write(`${eta}/package.json`, JSON.stringify({ name: 'eta', version: '5.0.0', license: 'MIT' }))
  write(`${eta}/LICENSE.md`, '# Eta license\nMIT, Eta authors\n\n# Bundled\n## dep-one\nDep licence\n')
})

afterAll(() => {
  rmSync(root, { recursive: true, force: true })
})

describe('packageDirOf', () => {
  it("resolves pnpm's layout to the real package folder", () => {
    expect(packageDirOf(`${root}/node_modules/.pnpm/alpha@1.0.0/node_modules/alpha/esm/index.js`)).toBe(
      pnpm('alpha@1.0.0', 'alpha'),
    )
  })

  it('keeps a scope with its name', () => {
    expect(packageDirOf(`${root}/node_modules/.pnpm/@scope+beta@2.0.0/node_modules/@scope/beta/dist/beta.js`)).toBe(
      pnpm('@scope+beta@2.0.0', '@scope/beta'),
    )
  })

  it('drops a query and reads Windows separators', () => {
    expect(packageDirOf('C:\\web\\node_modules\\react\\index.js?commonjs-proxy')).toBe('C:/web/node_modules/react')
  })

  it("skips virtual ids and the project's own files", () => {
    expect(packageDirOf('\0rolldown/runtime.js')).toBeNull()
    expect(packageDirOf(`${root}/src/main.tsx`)).toBeNull()
    expect(packageDirOf(`${root}/index.html`)).toBeNull()
  })
})

describe('buildNotices', () => {
  const ids = () => [
    `${root}/src/main.tsx`,
    `${pnpm('gamma@3.1.0', 'gamma')}/lib/gamma.js`,
    `${pnpm('alpha@1.0.0', 'alpha')}/index.js`,
    `${pnpm('alpha@1.0.0', 'alpha')}/esm/index.js`,
    `${pnpm('@scope+beta@2.0.0', '@scope/beta')}/dist/beta.js`,
  ]

  it('writes the opening, each package sorted by name, then the Mana entry', () => {
    const result = buildNotices(ids(), fsPackageReader)
    // By hand, from the format: name and version, the licence when
    // package.json names one, the repository when named, a blank line, the licence
    // files (CRLF read as LF, trailing blank lines dropped), and a line of
    // 72 dashes between entries. `@` sorts before letters.
    const expected = [
      NOTICES_OPENING,
      '',
      '@scope/beta 2.0.0',
      'ISC',
      'https://github.com/example/beta',
      '',
      NO_LICENCE_FILE,
      '',
      SEPARATOR,
      '',
      'alpha 1.0.0',
      'MIT',
      'https://github.com/example/alpha',
      '',
      'MIT License',
      '',
      'Copyright (c) Alpha authors',
      '',
      SEPARATOR,
      '',
      'gamma 3.1.0',
      '',
      'Gamma licence',
      '',
      'Gamma notice',
      '',
      SEPARATOR,
      '',
      MANA_ENTRY,
      '',
    ].join('\n')
    expect(result.text).toBe(expected)
    expect(result.packages).toEqual(['@scope/beta 2.0.0', 'alpha 1.0.0', 'gamma 3.1.0'])
    expect(result.withoutFile).toEqual(['@scope/beta 2.0.0'])
    expect(result.errors).toEqual([])
  })

  it('reports a package with neither a licence file nor a field', () => {
    const result = buildNotices([...ids(), `${pnpm('delta@0.1.0', 'delta')}/index.js`], fsPackageReader)
    expect(result.errors).toEqual(['delta 0.1.0: neither a licence file nor a license field'])
    expect(result.packages).not.toContain('delta 0.1.0')
  })

  it('reports a folder with no package.json', () => {
    const missing = `${root}/node_modules/.pnpm/zeta@1.0.0/node_modules/zeta`
    const result = buildNotices([`${missing}/index.js`], fsPackageReader)
    expect(result.errors).toEqual([`${missing}: no package.json`])
  })

  it('adds the extra folders by the same rule', () => {
    const result = buildNotices([], fsPackageReader, { extraDirs: [pnpm('epsilon@4.0.0', 'epsilon')] })
    expect(result.packages).toEqual(['epsilon 4.0.0'])
    expect(result.text).toBe(
      [NOTICES_OPENING, '', 'epsilon 4.0.0', 'MIT', '', 'Epsilon licence', '', SEPARATOR, '', MANA_ENTRY, ''].join('\n'),
    )
  })

  it('cuts a licence file at the heading named for its package', () => {
    const result = buildNotices([], fsPackageReader, {
      extraDirs: [pnpm('eta@5.0.0', 'eta')],
      cuts: { eta: { heading: '# Bundled' } },
    })
    // Everything from the heading on goes, and the blank line before it.
    expect(result.text).toBe(
      [NOTICES_OPENING, '', 'eta 5.0.0', 'MIT', '', '# Eta license', 'MIT, Eta authors', '', SEPARATOR, '', MANA_ENTRY, ''].join(
        '\n',
      ),
    )
    expect(result.errors).toEqual([])
  })

  it('fails a cut whose heading is missing', () => {
    const result = buildNotices([], fsPackageReader, {
      extraDirs: [pnpm('eta@5.0.0', 'eta')],
      cuts: { eta: { heading: '# Licenses of bundled dependencies' } },
    })
    expect(result.errors).toEqual(['eta 5.0.0: no licence file has the line "# Licenses of bundled dependencies" to cut it at'])
    expect(result.packages).toEqual([])
  })

  it('takes the extra files named for a package, after its licence files', () => {
    const result = buildNotices([], fsPackageReader, {
      extraDirs: [pnpm('theta@6.0.0', 'theta')],
      extraFiles: { theta: ['THIRD-PARTY-LICENSE'] },
    })
    expect(result.text).toBe(
      [NOTICES_OPENING, '', 'theta 6.0.0', 'MIT', '', 'Theta licence', '', 'Upstream licence', '', SEPARATOR, '', MANA_ENTRY, ''].join(
        '\n',
      ),
    )
    expect(result.errors).toEqual([])
  })

  it('fails an extra file that is missing', () => {
    const result = buildNotices([], fsPackageReader, {
      extraDirs: [pnpm('epsilon@4.0.0', 'epsilon')],
      extraFiles: { epsilon: ['THIRD-PARTY-LICENSE'] },
    })
    expect(result.errors).toEqual(['epsilon 4.0.0: no file THIRD-PARTY-LICENSE'])
    expect(result.packages).toEqual([])
  })

  it('maps a virtual id to the package its prefix names', () => {
    const result = buildNotices(['\0vite/preload-helper.js'], fsPackageReader, {
      virtualDirs: { '\0vite/': pnpm('epsilon@4.0.0', 'epsilon') },
    })
    expect(result.packages).toEqual(['epsilon 4.0.0'])
    expect(result.errors).toEqual([])
  })

  it('fails a virtual id no prefix names', () => {
    const result = buildNotices(['\0commonjsHelpers.js'], fsPackageReader, {
      virtualDirs: { '\0vite/': pnpm('epsilon@4.0.0', 'epsilon') },
    })
    expect(result.errors).toEqual(['virtual module \\0commonjsHelpers.js: no package is known for it'])
    expect(result.packages).toEqual([])
  })

  it("adds a notice file after the package's own licence, behind a line of dashes", () => {
    const result = buildNotices([], fsPackageReader, {
      extraDirs: [pnpm('iota@7.0.0', 'iota')],
      extraNotices: { iota: [`${root}/notices/iota-copied.txt`] },
    })
    expect(result.text).toBe(
      [
        NOTICES_OPENING,
        '',
        'iota 7.0.0',
        'ISC',
        '',
        'Iota licence',
        '',
        SEPARATOR,
        '',
        'iota copies part of Kappa, under:',
        '',
        'Kappa licence',
        '',
        SEPARATOR,
        '',
        MANA_ENTRY,
        '',
      ].join('\n'),
    )
    expect(result.errors).toEqual([])
  })

  it('fails a notice file that is missing', () => {
    const missing = `${root}/notices/none.txt`
    const result = buildNotices([], fsPackageReader, {
      extraDirs: [pnpm('iota@7.0.0', 'iota')],
      extraNotices: { iota: [missing] },
    })
    expect(result.errors).toEqual([`iota 7.0.0: no notice file ${missing}`])
    expect(result.packages).toEqual([])
  })

  it('fails a cut, extra file or notice keyed by a package not in the bundle', () => {
    const result = buildNotices([], fsPackageReader, {
      extraDirs: [pnpm('iota@7.0.0', 'iota')],
      cuts: { iotta: { heading: '# Bundled' } },
      extraFiles: { 'react-dom': ['THIRD-PARTY-LICENSE'] },
      extraNotices: { iota: [`${root}/notices/iota-copied.txt`], kappa: [`${root}/notices/iota-copied.txt`] },
    })
    expect(result.errors).toEqual([
      'cuts: no package in the bundle is named "iotta"',
      'extraFiles: no package in the bundle is named "react-dom"',
      'extraNotices: no package in the bundle is named "kappa"',
    ])
    expect(result.packages).toEqual(['iota 7.0.0'])
  })
})
