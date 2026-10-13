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
import { WelcomeView, type DownloadsAnswer, type WelcomeActions } from './WelcomeView'

// The view is drawn to static markup with a fake shell's settings: no DOM,
// so these pin what each step says in each state, not what a press does.
// (Presses are the settings components' own, tested where they live.)

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
function render(
  step: WelcomeStep,
  given: { sources?: Sources; app?: AppSettings; downloads?: DownloadsAnswer } = {},
): { text: string; html: string } {
  const html = renderToStaticMarkup(
    createElement(
      MemoryRouter,
      null,
      createElement(WelcomeView, {
        step,
        sources: given.sources ?? sources(),
        app: given.app ?? app(),
        downloads: given.downloads ?? 'loading',
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

describe('the frame', () => {
  it('numbers each step out of six, under its heading', () => {
    expect(render('language').text).toContain('Step 1 of 6 Language')
    expect(render('welcome').text).toContain('Step 2 of 6 Welcome to Sensei Top')
    expect(render('arena').text).toContain('Step 3 of 6 Arena')
    expect(render('cards').text).toContain('Step 4 of 6 Card data')
    expect(render('mtgo').text).toContain('Step 5 of 6 Magic Online')
    expect(render('done').text).toContain('Step 6 of 6 Ready')
  })

  it('has no Back on step 1, and links the neighbours by their addresses', () => {
    const first = render('language')
    expect(first.text).not.toContain('Back')
    expect(first.html).toContain('href="/welcome?step=welcome"')
    const middle = render('arena')
    expect(middle.html).toContain('href="/welcome?step=welcome"')
    expect(middle.html).toContain('href="/welcome?step=cards"')
    expect(render('done').html).toContain('href="/welcome?step=mtgo"')
  })
})

describe('step 1', () => {
  it('offers the two languages, never System, and starts the run', () => {
    const { text, html } = render('language')
    expect(text).toContain(welcome.language.body)
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
      const checked = render('language').html.match(/aria-checked="true"[^>]*>([^<]*)</g) ?? []
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
      expect(render('language').html).toMatch(/aria-checked="true"[^>]*>Português \(Brasil\)</)
      setLanguage('en')
      expect(apiLanguage()).toBe('en')
      expect(render('language').html).toMatch(/aria-checked="true"[^>]*>English</)
    } finally {
      setLanguage('en')
    }
  })
})

describe('step 2', () => {
  it('carries the keyed notice and the three things that leave', () => {
    const { text } = render('welcome')
    expect(text).toContain(welcome.intro.wizardsNotice)
    expect(text).toContain('What leaves this computer')
    expect(text).toContain('Nothing about your games is sent.')
    expect(text).toContain('A daily check for a new version of the app.')
    expect(text).toContain('Check for updates')
    expect(text).toContain('Writing with Claude, only if you add your own Claude key')
    expect(text).toContain('Next')
  })

  it('keys the Wizards notice without a byte of change', () => {
    expect(welcome.intro.wizardsNotice).toBe(
      'Sensei Top is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.',
    )
  })

  it('links to the credits', () => {
    const { html, text } = render('welcome')
    expect(html).toMatch(/href="\/settings#credits"[^>]*>Settings, under About and credits<\/a>/)
    expect(text).toContain('Every source and its terms are listed in Settings, under About and credits')
  })

  it('says so, with no switch, where the copy does not update itself', () => {
    const { text } = render('welcome', { app: app({ update: { state: 'unavailable', reason: 'store' } }) })
    expect(text).toContain('This copy does not check for new versions itself.')
    expect(text).not.toContain('A daily check')
    expect(text).not.toContain('Check for updates')
  })
})

describe('step 3', () => {
  it('is quiet when Detailed Logs are on', () => {
    const { text } = render('arena')
    expect(text).toContain("The app found Arena's log, and Detailed Logs are on.")
    expect(text).toContain('Log file /arena/Player.log')
    expect(text).not.toContain('Check again')
    expect(text).not.toContain('Tick Detailed Logs')
  })

  it('gives the steps and a check when it has not seen the line', () => {
    const { text } = render('arena', { sources: sources({}, { detailedLogs: 'unknown' }) })
    expect(text).toContain('has not seen the line where Arena says Detailed Logs are on')
    expect(text).toContain('In Arena, open Options, then Account.')
    expect(text).toContain('Tick Detailed Logs (Plugin Support).')
    expect(text).toContain('Close Arena and start it again.')
    expect(text).toContain('Check again')
  })

  it('gives the steps and a check when they are off', () => {
    const { text } = render('arena', { sources: sources({}, { detailedLogs: 'disabled' }) })
    expect(text).toContain("Arena's log says Detailed Logs are off.")
    expect(text).toContain('Tick Detailed Logs (Plugin Support).')
    expect(text).toContain('Check again')
  })

  it('says it found no log, with a check but no steps', () => {
    const { text } = render('arena', { sources: sources({}, { path: null, found: false, detailedLogs: 'unknown' }) })
    expect(text).toContain("The app did not find Arena's log.")
    expect(text).toContain('Check again')
    expect(text).not.toContain('Log file')
    expect(text).not.toContain('Tick Detailed Logs')
  })

  it('offers the restore before any data is written', () => {
    const { text } = render('arena')
    expect(text).toContain('Used Sensei Top before?')
    expect(text).toContain('a restore replaces what this computer has recorded')
    expect(text).toContain('Choose a backup file')
  })
})

describe('step 4', () => {
  it('offers the download first when there is no rules text', () => {
    expect(render('cards').text).toContain('Download card data')
    expect(render('cards', { app: withFirstData({ state: 'idle' }, 0) }).text).toContain('Download card data')
    expect(render('cards').text).toContain('a download of about 80 MB')
  })

  it('offers it again when the computer already has rules text', () => {
    const { text } = render('cards', { app: withFirstData({ state: 'idle' }, 31000) })
    expect(text).toContain('This computer already has rules text for 31,000 cards.')
    expect(text).toContain('Download again')
    expect(text).not.toContain('Download card data')
  })

  it('words the download stage from the shell\'s progress, with a determinate meter, and offers to skip', () => {
    const total = render('cards', {
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
    expect(total.text).toContain('Skip, do it in the background')
    expect(total.text).not.toContain('Download card data')
    const unknown = render('cards', {
      app: withFirstData({ state: 'running', line: null, progress: { stage: 'download', done: 34_400_000, total: null } }),
    })
    expect(unknown.text).toContain('Downloading card data: 34 MB so far.')
    expect(unknown.html).toContain('animate-pulse')
  })

  it('says the save stage takes a few minutes, with an indeterminate meter', () => {
    const save = render('cards', { app: withFirstData({ state: 'running', line: null, progress: { stage: 'save' } }) })
    expect(save.text).toContain('Saving cards to the database. This takes a few minutes.')
    expect(save.html).toContain('animate-pulse')
    expect(save.html).not.toContain('aria-valuenow')
  })

  it('says it is starting before any progress arrives', () => {
    const bare = render('cards', { app: withFirstData({ state: 'running', line: null }) })
    expect(bare.text).toContain('Starting the download.')
    expect(bare.html).toContain('animate-pulse')
  })

  it('tells the new copy above the button', () => {
    expect(render('cards').text).toContain(
      'a download of about 80 MB that then takes a few minutes to unpack and save. The deck guides need them. You can go on while it runs.',
    )
  })

  it('never shows the last line of a finished download', () => {
    const done = render('cards', {
      app: withFirstData({ state: 'done', line: '31000 cards stored in /secret/place.db' }, 31000),
    })
    expect(done.text).toContain('Card data is in: rules text for 31,000 cards.')
    expect(done.text).not.toContain('/secret/place.db')
    for (const none of [null, 0]) {
      const text = render('cards', { app: withFirstData({ state: 'done', line: 'x' }, none) }).text
      expect(text).toContain('Card data is in. ')
      expect(text).not.toContain('rules text for')
    }
  })

  it('says why it failed, with one full stop, and offers to try again', () => {
    const stopped = render('cards', { app: withFirstData({ state: 'failed', error: 'The download was stopped.' }) })
    expect(stopped.text).toContain('The download failed: The download was stopped. ')
    expect(stopped.text).not.toContain('stopped..')
    expect(stopped.text).toContain('Try again')
    const plain = render('cards', { app: withFirstData({ state: 'failed', error: 'No network' }) })
    expect(plain.text).toContain('The download failed: No network.')
  })

  it('names the two background downloads by the age the status gives', () => {
    const { text } = render('cards', { downloads: { archetypeHours: 5, corpusHours: 100 } })
    expect(text).toContain('Archetype definitions Updated 5 hours ago')
    expect(text).toContain('Tournament results Updated 4 days ago')
    expect(text).toContain('These run in the background whenever the app is open')
    expect(render('cards', { downloads: { archetypeHours: null, corpusHours: 0.5 } }).text).toContain(
      'Archetype definitions Not yet Tournament results Updated less than an hour ago',
    )
  })

  it('says nothing while the status loads and not known when it failed', () => {
    const loading = render('cards', { downloads: 'loading' }).text
    expect(loading).not.toContain('Not known')
    expect(loading).not.toContain('Not yet')
    expect(loading).not.toContain('Updated')
    const failed = render('cards', { downloads: 'failed' }).text
    expect(failed).toContain('Archetype definitions Not known Tournament results Not known')
  })

  it('makes the forward button quiet only while the download button is the primary one', () => {
    const primary = (html: string) => /bg-accent[^"]*"[^>]*>(Next|Skip)/.test(html)
    expect(primary(render('cards').html)).toBe(false)
    expect(primary(render('cards', { app: withFirstData({ state: 'idle' }, 5) }).html)).toBe(true)
    expect(primary(render('mtgo').html)).toBe(false)
    expect(primary(render('arena').html)).toBe(true)
  })

  it('goes on with Next while nothing runs', () => {
    expect(render('cards').text).toContain('Next')
    expect(render('cards').text).not.toContain('Skip, do it')
  })
})

describe('step 5', () => {
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
    expect(text).toContain('files named Match_GameLog')
    expect(text).toContain('AppData\\Local\\Apps\\2.0\\Data')
    expect(text).toContain("inside that prefix's drive_c folder")
  })

  it('asks for the name and why, and offers the folder picker', () => {
    const { text } = render('mtgo')
    expect(text).toContain('Skip this step if you do not play Magic Online.')
    expect(text).toContain('Your name on Magic Online')
    expect(text).toContain('Magic Online\'s log never says which player is you')
    expect(text).toContain('Folder of game logs')
    expect(text).toContain('Choose a folder')
  })
})

describe('step 6', () => {
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
    expect(text).toContain('It starts in the background and records your games without you opening it.')
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
    expect(html).not.toContain('Step 3 of 6')
  })
})
