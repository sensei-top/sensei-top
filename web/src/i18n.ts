import i18next, { type InitOptions, type Resource, type ResourceLanguage, type TFunction } from 'i18next'
import { useSyncExternalStore } from 'react'
import { initReactI18next } from 'react-i18next'
import { startShellStore, type LanguageChoice } from './bridge'

/**
 * The dashboard's translation layer. Every catalogue is a JSON file,
 * `locales/<language>/<namespace>.json`, one namespace per area, picked up
 * by the glob below: no file registers one by hand. English is the source
 * catalogue and the fallback, so a language or a key with no entry yet reads
 * as English.
 *
 * A key is written whole, its namespace first: `t('shell.liveStatus.down')`
 * is `liveStatus.down` in `locales/<language>/shell.json`. The namespace
 * separator is the key separator, which i18next allows when the first part
 * names a namespace it was given (`NAMESPACES`).
 */

export type { LanguageChoice } from './bridge'
export type { TFunction } from 'i18next'

/** The languages the dashboard can be read in. */
export const LANGUAGES = ['en', 'pt-BR'] as const
export type Language = (typeof LANGUAGES)[number]

/** The source catalogue, and what any missing entry falls back to. */
export const FALLBACK_LANGUAGE: Language = 'en'

const STORAGE_KEY = 'sensei-top:language'

/** Builds i18next's resources from the catalogue files, keyed by their path
 *  (`./locales/en/shell.json`). A path of any other shape is skipped. */
export function resourcesFrom(files: Record<string, ResourceLanguage>): Resource {
  const resources: Resource = {}
  for (const [path, catalogue] of Object.entries(files)) {
    const parts = /\/locales\/([^/]+)\/([^/]+)\.json$/.exec(path)
    if (!parts) continue
    const [, language, namespace] = parts
    resources[language] = { ...resources[language], [namespace]: catalogue }
  }
  return resources
}

const RESOURCES = resourcesFrom(
  import.meta.glob<ResourceLanguage>('./locales/*/*.json', { eager: true, import: 'default' }),
)

/** Every namespace any language has a catalogue for. */
export const NAMESPACES: readonly string[] = [
  ...new Set(Object.values(RESOURCES).flatMap((language) => Object.keys(language))),
].sort()

const OPTIONS: InitOptions = {
  resources: RESOURCES,
  ns: [...NAMESPACES],
  defaultNS: false,
  fallbackLng: FALLBACK_LANGUAGE,
  supportedLngs: [...LANGUAGES],
  nonExplicitSupportedLngs: false,
  load: 'currentOnly',
  nsSeparator: '.',
  keySeparator: '.',
  // React escapes what it renders.
  interpolation: { escapeValue: false },
  returnNull: false,
  // The catalogues are bundled, so nothing is waited for: `t` answers as soon
  // as `init` returns.
  initAsync: false,
}

/** A `t` of its own for one language, apart from the dashboard's: for a test
 *  of a function that takes `t`, which then reads the real catalogues. */
export function translator(language: Language): TFunction {
  const instance = i18next.createInstance()
  void instance.init({ ...OPTIONS, lng: language })
  return instance.t
}

/** The language a "system" choice means for the viewer's languages, in
 *  their order of preference: the first one the dashboard has, Portuguese
 *  of any region giving `pt-BR`. English when none is. */
export function systemLanguage(languages: readonly string[]): Language {
  for (const tag of languages) {
    const lower = tag.toLowerCase()
    if (lower === 'pt' || lower.startsWith('pt-')) return 'pt-BR'
    if (lower === 'en' || lower.startsWith('en-')) return 'en'
  }
  return FALLBACK_LANGUAGE
}

function viewerLanguages(): readonly string[] {
  const nav = globalThis.navigator as Navigator | undefined
  if (nav?.languages?.length) return nav.languages
  return nav?.language ? [nav.language] : []
}

/** The language a choice means right now. */
export function languageOf(choice: LanguageChoice): Language {
  return choice === 'system' ? systemLanguage(viewerLanguages()) : choice
}

function isChoice(value: unknown): value is LanguageChoice {
  return value === 'system' || (LANGUAGES as readonly unknown[]).includes(value)
}

/** The shell's own preference, where a shell is there and sends one. An
 *  older shell sends none, and the page then keeps its own. */
function shellChoice(): LanguageChoice | null {
  const language: unknown = startShellStore().snapshot()?.app?.settings.language
  return isChoice(language) ? language : null
}

// A private window or blocked storage must never break the language itself.
function storedChoice(): LanguageChoice | null {
  try {
    if (typeof window === 'undefined') return null
    const stored = window.localStorage.getItem(STORAGE_KEY)
    return isChoice(stored) ? stored : null
  } catch {
    return null
  }
}

function storeChoice(choice: LanguageChoice) {
  try {
    if (typeof window !== 'undefined') window.localStorage.setItem(STORAGE_KEY, choice)
  } catch {
    // per-viewer convenience only, like the density
  }
}

type State = { choice: LanguageChoice; language: Language }

let state: State = (() => {
  const choice = shellChoice() ?? storedChoice() ?? 'system'
  return { choice, language: languageOf(choice) }
})()

const stateListeners = new Set<() => void>()
const changeListeners = new Set<(language: Language) => void>()

function markDocument() {
  if (typeof document !== 'undefined') document.documentElement.lang = i18next.resolvedLanguage ?? FALLBACK_LANGUAGE
}

void i18next.use(initReactI18next).init({ ...OPTIONS, lng: state.language })
markDocument()

/** The dashboard's `t`, for code outside a component (`lib/time.ts`'s
 *  `ago`). Call it where the text is built, never at module load: it answers
 *  in the language of that moment. A component takes `t` from
 *  `useTranslation()` instead, which also re-renders it on a change. */
export function currentT(): TFunction {
  return i18next.t
}

function apply(choice: LanguageChoice) {
  const language = languageOf(choice)
  if (choice === state.choice && language === state.language) return
  const changed = language !== state.language
  state = { choice, language }
  if (changed) {
    void i18next.changeLanguage(language).then(markDocument)
    for (const listener of [...changeListeners]) listener(language)
  }
  for (const listener of [...stateListeners]) listener()
}

/** Chooses the language: "system", or one of `LANGUAGES`. The page switches
 *  at once. A shell keeps the choice in `shell.json`; with no shell it is
 *  kept in this browser's storage (which is written either way). */
export function setLanguage(choice: LanguageChoice): void {
  storeChoice(choice)
  apply(choice)
  const app = startShellStore().snapshot()?.app
  if (app) app.set({ language: choice }).catch(() => {})
}

// The shell's preference follows the shell: a change it publishes is applied.
// Only a change of that preference: the shell publishes for other reasons
// too, and those must not undo a choice made on the page since.
let shellLanguage = shellChoice()
startShellStore().subscribe(() => {
  const choice = shellChoice()
  if (choice === shellLanguage) return
  shellLanguage = choice
  if (choice) apply(choice)
})

// "System" follows the browser's own languages when they change.
if (typeof window !== 'undefined') {
  window.addEventListener('languagechange', () => {
    if (state.choice === 'system') apply('system')
  })
}

/** The language the API is asked to write in, sent as `Accept-Language` on
 *  every request: the choice as it resolves now. A language with no
 *  catalogue yet is still asked for, since the API has catalogues of its
 *  own. */
export function apiLanguage(): Language {
  return languageOf(state.choice)
}

/** Calls `listener` once for each change of the language itself (not of a
 *  choice that resolves to the same one); returns a function that stops it.
 *  `main.tsx` resets the query cache here, so the API's prose is asked for
 *  again in the new language. */
export function onLanguageChange(listener: (language: Language) => void): () => void {
  changeListeners.add(listener)
  return () => void changeListeners.delete(listener)
}

function subscribe(listener: () => void) {
  stateListeners.add(listener)
  return () => void stateListeners.delete(listener)
}

const snapshot = () => state

/** The language in use, the choice behind it, and the setter, for the
 *  control on `/settings`. */
export function useLanguage(): {
  language: Language
  choice: LanguageChoice
  setLanguage: (choice: LanguageChoice) => void
} {
  const { choice, language } = useSyncExternalStore(subscribe, snapshot, snapshot)
  return { language, choice, setLanguage }
}
