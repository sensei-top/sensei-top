import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { AppSettings, FirstData, ShellSettings } from '../bridge'
import { apiLanguage, setLanguage } from '../i18n'
import welcome from '../locales/en/welcome.json'
import type { WelcomeStep } from '../lib/welcome'
import { WelcomePage } from '../pages/WelcomePage'
import { WelcomeView, type WelcomeActions } from './WelcomeView'

// The view is drawn to static markup with a fake shell's settings: no DOM,
// so these pin what each step says in each state, not what a press does.
// (Presses are the settings components' own, tested where they live.) The
// expected words are the approved copy's (plan 23, S0).

const ok = () => Promise.resolve({ ok: true } as const)

const actions: WelcomeActions = {
  set: ok,
  recheck: ok,
  firstData: ok,
  finishOnboarding: ok,
  save: ok,
  pickFolder: () => Promise.resolve(null),
  pickFile: () => Promise.resolve(null),
  restoreFrom: ok,
}

type Sources = ShellSettings['sources']

function sources(change: Partial<Sources> = {}, arenaLog: Partial<Sources['arenaLog']> = {}): Sources {
  return {
    arenaLog: { path: '/arena/Player.log', found: true, detailedLogs: 'enabled', ...arenaLog },
    dateOrder: 'auto',
    mtgoHandle: null,
    mtgoDir: null,
    mtgoDeckDir: null,
    mtgoFound: null,
    dataDir: '/data',
    ...change,
  }
}

function app(change: Partial<AppSettings> = {}): AppSettings {
  return {
    startWithSystem: false,
    keepRunningOnClose: false,
    checkForUpdates: true,
    diagnostic: false,
    update: { state: 'idle' },
    onboarded: false,
    askAutostart: false,
    rulesText: null,
    firstData: { state: 'idle' },
    version: '1.0.0',
    platform: 'linux',
    ...change,
  }
}

/** The step as visible text: tags dropped, entities read, spaces collapsed. */
function render(step: WelcomeStep, given: { sources?: Sources; app?: AppSettings } = {}): { text: string; html: string } {
  const html = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(WelcomeView, {
        step,
        sources: given.sources ?? sources(),
        app: given.app ?? app(),
        actions,
        onFinished: () => {},
      }),
    ),
  )
  const text = html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()
  return { text, html }
}

const withFirstData = (firstData: FirstData, rulesText: number | null = null) => app({ firstData, rulesText })

/** The drawing is one image labelled with the whole instruction. */
const GUIDE = 'aria-label="In Arena, open Options, then Account, and tick Detailed Logs (Plugin Support). Then close Arena and start it again."'

describe('the frame', () => {
  it('numbers each step out of five when both clients are played, under its heading', () => {
    expect(render('start').text).toContain('Step 1 of 5 Welcome to Sensei Top')
    expect(render('plays').text).toContain('Step 2 of 5 Which do you play?')
    expect(render('arena').text).toContain('Step 3 of 5 Arena')
    expect(render('mtgo').text).toContain('Step 4 of 5 Magic Online')
    expect(render('done').text).toContain('Step 5 of 5 Ready')
  })

  it('counts only the client chosen', () => {
    expect(render('arena', { app: app({ plays: ['arena'] }) }).text).toContain('Step 3 of 4 Arena')
    expect(render('done', { app: app({ plays: ['arena'] }) }).text).toContain('Step 4 of 4 Ready')
    expect(render('mtgo', { app: app({ plays: ['mtgo'] }) }).text).toContain('Step 3 of 4 Magic Online')
    expect(render('done', { app: app({ plays: ['mtgo'] }) }).text).toContain('Step 4 of 4 Ready')
  })

  it('has no Back on Start, and links the neighbours by their addresses', () => {
    const first = render('start')
    expect(first.text).not.toContain('Back')
    expect(first.html).toContain('href="/welcome?step=plays"')
    const middle = render('arena')
    expect(middle.html).toContain('href="/welcome?step=plays"')
    expect(middle.html).toContain('href="/welcome?step=mtgo"')
    expect(render('done').html).toContain('href="/welcome?step=mtgo"')
  })

  it('passes over the client not chosen', () => {
    const arenaOnly = app({ plays: ['arena'] })
    expect(render('arena', { app: arenaOnly }).html).toContain('href="/welcome?step=done"')
    expect(render('done', { app: arenaOnly }).html).toContain('href="/welcome?step=arena"')
    const mtgoOnly = app({ plays: ['mtgo'] })
    expect(render('mtgo', { app: mtgoOnly }).html).toContain('href="/welcome?step=plays"')
    expect(render('done', { app: mtgoOnly }).html).toContain('href="/welcome?step=mtgo"')
  })

  it('makes the forward button quiet only where the step has its own control to press', () => {
    const primary = (html: string) => /bg-accent[^"]*"[^>]*>(Next|Start)</.test(html)
    expect(primary(render('start').html)).toBe(true)
    expect(primary(render('arena').html)).toBe(true)
    expect(primary(render('plays').html)).toBe(false)
    expect(primary(render('mtgo').html)).toBe(false)
  })
})

describe('Start', () => {
  it('offers the two languages, never System, and starts the run', () => {
    const { text, html } = render('start')
    expect(html).toContain('aria-label="Language"')
    expect(html).toContain('>English<')
    expect(html).toContain('>Português (Brasil)<')
    expect(html.match(/role="radio"/g)).toHaveLength(2)
    expect(text).not.toContain('System')
    expect(text).toContain('Start')
  })

  it('pre-selects what a system choice resolves to', () => {
    const languages = Object.getOwnPropertyDescriptor(globalThis.navigator, 'languages')
    Object.defineProperty(globalThis.navigator, 'languages', { value: ['pt-BR'], configurable: true })
    try {
      setLanguage('system')
      const checked = render('start').html.match(/aria-checked="true"[^>]*>([^<]*)</g) ?? []
      expect(checked).toHaveLength(1)
      expect(checked[0]).toContain('Português (Brasil)')
    } finally {
      if (languages) Object.defineProperty(globalThis.navigator, 'languages', languages)
      else Reflect.deleteProperty(globalThis.navigator, 'languages')
      setLanguage('en')
    }
  })

  it('draws the checked option from the language in use', () => {
    try {
      setLanguage('pt-BR')
      expect(apiLanguage()).toBe('pt-BR')
      expect(render('start').html).toMatch(/aria-checked="true"[^>]*>Português \(Brasil\)</)
      setLanguage('en')
      expect(apiLanguage()).toBe('en')
      expect(render('start').html).toMatch(/aria-checked="true"[^>]*>English</)
    } finally {
      setLanguage('en')
    }
  })

  it('says the promise in one sentence and keeps the Wizards notice', () => {
    const { text } = render('start')
    expect(text).toContain(
      'Your match history and game reviews, from the logs Arena and Magic Online already write. Nothing about your games leaves this computer.',
    )
    expect(text).toContain(welcome.intro.wizardsNotice)
  })

  it('keys the Wizards notice without a byte of change', () => {
    expect(welcome.intro.wizardsNotice).toBe(
      'Sensei Top is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.',
    )
  })

  it('keeps what leaves this computer behind a closed disclosure, with no switch', () => {
    const { text, html } = render('start')
    expect(html).toMatch(/<details[^>]*>\s*<summary[^>]*>.*What leaves this computer<\/summary>/)
    expect(html).not.toMatch(/<details[^>]*open/)
    const inside = html.slice(html.indexOf('<details'), html.indexOf('</details>'))
    expect(inside).toContain('Nothing about your games is sent.')
    expect(inside).toContain('A daily check for a new version of the app.')
    expect(inside).toContain('Writing with Claude, only if you add your own Claude key')
    expect(inside).not.toContain('role="switch"')
    expect(text).not.toContain('Check for a new version once a day')
  })

  it('links to the credits inside the disclosure', () => {
    const { html } = render('start')
    const inside = html.slice(html.indexOf('<details'), html.indexOf('</details>'))
    expect(inside).toMatch(/href="\/settings#credits"[^>]*>Settings, under About and credits<\/a>/)
  })

  it('says so where the copy does not update itself', () => {
    const { text } = render('start', { app: app({ update: { state: 'unavailable', reason: 'store' } }) })
    expect(text).toContain('This copy does not check for new versions itself.')
    expect(text).not.toContain('A daily check')
  })

  it('offers the restore, also while card data downloads', () => {
    const { text } = render('start')
    expect(text).toContain('Used Sensei Top before? Restore a backup')
    const running = render('start', { app: withFirstData({ state: 'running', line: null }) }).html
    expect(running).toMatch(/<button(?![^>]*\sdisabled="")[^>]*>Restore a backup</)
  })
})

describe('Which do you play?', () => {
  it('offers three tiles, Both pressed on a first run, since the shell sends both until a pick', () => {
    const { text, html } = render('plays', { app: app({ plays: ['arena', 'mtgo'] }) })
    expect(text).toContain('The next steps set up only what you pick.')
    expect(html).toMatch(/aria-pressed="false"[^>]*>Arena</)
    expect(html).toMatch(/aria-pressed="false"[^>]*>Magic Online</)
    expect(html).toMatch(/aria-pressed="true"[^>]*>(?:<svg.*?<\/svg>)?Both</)
    expect(html.match(/aria-pressed="true"/g)).toHaveLength(1)
  })

  it('marks nothing from a shell older than the choice, which sends none', () => {
    for (const plays of [undefined, []]) {
      const { html } = render('plays', { app: app({ plays }) })
      expect(html.match(/aria-pressed="false"/g)).toHaveLength(3)
      expect(html).not.toContain('aria-pressed="true"')
    }
  })

  it('marks the saved choice when the step is revisited', () => {
    const pressed = (plays: AppSettings['plays']) =>
      (render('plays', { app: app({ plays }) }).html.match(/aria-pressed="true"[^>]*>(?:<svg.*?<\/svg>)?([^<]*)</) ?? [])[1]
    expect(pressed(['arena'])).toBe('Arena')
    expect(pressed(['mtgo'])).toBe('Magic Online')
    expect(pressed(['arena', 'mtgo'])).toBe('Both')
  })
})

describe('Arena', () => {
  it('is quiet when Detailed Logs are on: no drawing, no check', () => {
    const { text, html } = render('arena')
    expect(text).toContain("The app found Arena's log, and Detailed Logs are on.")
    expect(html).toContain('bg-win')
    expect(text).toContain('Log file /arena/Player.log')
    expect(text).not.toContain('Check again')
    expect(html).not.toContain(GUIDE)
  })

  it('shows the drawing and a check when the log does not say they are on', () => {
    const { text, html } = render('arena', { sources: sources({}, { detailedLogs: 'unknown' }) })
    expect(text).toContain(
      "The app found Arena's log, but it does not say Detailed Logs are on yet. Without them, no match is recorded.",
    )
    expect(html).toContain('bg-warn')
    expect(html).toContain(GUIDE)
    expect(text).toContain('Check again')
    expect(text).toContain('Log file /arena/Player.log')
  })

  it('shows the drawing and a check when they are off', () => {
    const { text, html } = render('arena', { sources: sources({}, { detailedLogs: 'disabled' }) })
    expect(text).toContain("Arena's log says Detailed Logs are off. Without them, no match is recorded.")
    expect(html).toContain(GUIDE)
    expect(text).toContain('Check again')
  })

  it('says it found no log, with the drawing and a check but no log file', () => {
    const { text, html } = render('arena', { sources: sources({}, { path: null, found: false, detailedLogs: 'unknown' }) })
    expect(text).toContain("The app did not find Arena's log. If Arena is installed, start it once, then check again.")
    expect(html).toContain('bg-loss')
    expect(html).toContain(GUIDE)
    expect(text).toContain('Check again')
    expect(text).not.toContain('Log file')
  })

  it('always lets the person go on', () => {
    const { html } = render('arena', { sources: sources({}, { detailedLogs: 'unknown' }) })
    expect(html).toMatch(/<a[^>]*href="\/welcome\?step=mtgo"[^>]*>Next</)
  })

  it('no longer carries the restore', () => {
    expect(render('arena').text).not.toContain('Restore a backup')
  })
})

describe('Magic Online', () => {
  it('starts from the saved folder', () => {
    const { text, html } = render('mtgo', { sources: sources({ mtgoDir: '/mtgo/logs', mtgoFound: '/other' }) })
    expect(html).toContain('value="/mtgo/logs"')
    expect(text).toContain('Each game is read once it ends.')
  })

  it('fills the folder the app found, and says Save reads it', () => {
    const { text, html } = render('mtgo', { sources: sources({ mtgoFound: '/found/logs' }) })
    expect(html).toContain('value="/found/logs"')
    expect(text).toContain('Magic Online is writing its game logs here. Save to read them.')
  })

  it('tells where the folder is when none is saved or found', () => {
    const { text, html } = render('mtgo')
    expect(html).not.toContain('value="/')
    expect(text).toContain(
      "Where Magic Online writes Match_GameLog files: AppData\\Local\\Apps\\2.0\\Data, or the prefix's drive_c under Wine or Proton.",
    )
  })

  it('asks for the name, the log folder and the deck folder, with no skip line', () => {
    const { text } = render('mtgo')
    expect(text).toContain('Your name on Magic Online')
    expect(text).toContain('The log never says which player is you.')
    expect(text).toContain('Folder of game logs')
    expect(text).toContain('Folder of decks')
    expect(text).toContain('Optional: where you export .dek files.')
    expect(text).toContain('Choose a folder')
    expect(text).not.toContain('Skip this step')
  })

  it('starts the deck folder from the saved one', () => {
    const { html } = render('mtgo', { sources: sources({ mtgoDeckDir: '/mtgo/decks' }) })
    expect(html).toContain('value="/mtgo/decks"')
  })
})

describe('Ready', () => {
  it('goes Home and ends the run', () => {
    const { text } = render('done')
    expect(text).toContain('Play a match. It appears on Home when it ends.')
    expect(text).toContain('Go to Home')
    expect(text).not.toContain('Start Sensei Top when you log in')
  })

  it('has Go to Home as the primary forward button in the foot row, after Back', () => {
    const { html } = render('done')
    const back = html.indexOf('>Back<')
    const home = html.indexOf('>Go to Home<')
    expect(back).toBeGreaterThan(-1)
    expect(home).toBeGreaterThan(back)
    expect(html.slice(html.lastIndexOf('<button', home), home)).toContain('bg-accent')
    expect(html.indexOf('Play a match.')).toBeLessThan(back)
  })

  it('asks about starting with the system only where the shell says to', () => {
    const { text } = render('done', { app: app({ askAutostart: true }) })
    expect(text).toContain('Start Sensei Top when you log in')
    expect(text).toContain('It records your games without you opening it.')
  })

  it('carries the update check, and hides it in a build without an updater', () => {
    expect(render('done').text).toContain('Check for a new version once a day')
    const store = render('done', { app: app({ update: { state: 'unavailable', reason: 'store' } }) }).text
    expect(store).not.toContain('Check for a new version once a day')
    expect(store).not.toContain('This copy does not check')
  })

  it('says nothing of card data while it is idle, whatever the count', () => {
    for (const count of [null, 0, 31000]) {
      const { text, html } = render('done', { app: withFirstData({ state: 'idle' }, count) })
      expect(text).not.toContain('Card data')
      expect(text).not.toContain('Download')
      expect(html).not.toContain('aria-label="Card data download"')
    }
  })

  it('words the download stage from the shell\'s progress, with a determinate meter', () => {
    const total = render('done', {
      app: withFirstData({
        state: 'running',
        line: 'ignored',
        progress: { stage: 'download', done: 34_400_000, total: 78_780_188 },
      }),
    })
    expect(total.text).toContain('Downloading card data: 34 of 79 MB.')
    expect(total.text).not.toContain('ignored')
    expect(total.html).toContain('aria-label="Card data download"')
    expect(total.html).toContain('aria-valuenow="44"')
    expect(total.html).not.toContain('animate-pulse')
    const unknown = render('done', {
      app: withFirstData({ state: 'running', line: null, progress: { stage: 'download', done: 34_400_000, total: null } }),
    })
    expect(unknown.text).toContain('Downloading card data: 34 MB so far.')
    expect(unknown.html).toContain('animate-pulse')
  })

  it('says the save stage takes a few minutes, with an indeterminate meter', () => {
    const save = render('done', { app: withFirstData({ state: 'running', line: null, progress: { stage: 'save' } }) })
    expect(save.text).toContain('Saving cards to the database. This takes a few minutes.')
    expect(save.html).toContain('animate-pulse')
    expect(save.html).not.toContain('aria-valuenow')
  })

  it('says it is starting before any progress arrives', () => {
    const bare = render('done', { app: withFirstData({ state: 'running', line: null }) })
    expect(bare.text).toContain('Starting the download.')
    expect(bare.html).toContain('animate-pulse')
  })

  it('never shows the last line of a finished download', () => {
    const done = render('done', {
      app: withFirstData({ state: 'done', line: '31000 cards stored in /secret/place.db' }, 31000),
    })
    expect(done.text).toContain('Card data is in: rules text for 31,000 cards.')
    expect(done.text).not.toContain('/secret/place.db')
    for (const none of [null, 0]) {
      const text = render('done', { app: withFirstData({ state: 'done', line: 'x' }, none) }).text
      expect(text).toContain('Card data is in. ')
      expect(text).not.toContain('rules text for')
    }
  })

  it('says why card data failed, with one full stop, and offers to try again', () => {
    const stopped = render('done', { app: withFirstData({ state: 'failed', error: 'The download was stopped.' }) })
    expect(stopped.text).toContain('The card data download failed: The download was stopped. ')
    expect(stopped.text).not.toContain('stopped..')
    expect(stopped.text).toContain('Try again')
    const plain = render('done', { app: withFirstData({ state: 'failed', error: 'No network' }) })
    expect(plain.text).toContain('The card data download failed: No network.')
  })
})

describe('the page', () => {
  it('is no page in a browser, which has no shell', () => {
    const html = renderToStaticMarkup(
      createElement(
        QueryClientProvider,
        { client: new QueryClient() },
        createElement(MemoryRouter, { initialEntries: ['/welcome?step=arena'] }, createElement(WelcomePage)),
      ),
    )
    expect(html).toContain('Nothing is at this address.')
    expect(html).not.toContain('Step 3 of')
  })
})
