import { useSyncExternalStore } from 'react'

/**
 * What a desktop shell hands the dashboard: its settings, and the functions
 * that change them. The Electron shell in `desktop/` fills `useShell()`
 * through `window.senseiTopShell`, set by its preload script; a browser has
 * none, so here it answers `null` and every page draws what the API alone
 * can say. A component takes the parts it shows as props and never reads
 * this module's hook itself, so a change of the shell's shape is a change
 * of one mapping, in the page that calls `useShell()`. The one exception is
 * `CopyPromptBody`, which asks only whether a shell exists (to hide the
 * import command), never its shape.
 */

/** Every field of `T` optional, at every depth; an array is taken whole. */
export type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends readonly unknown[] ? T[K] : T[K] extends object ? DeepPartial<T[K]> : T[K]
}

/** A save's answer. `error` is a sentence the shell wrote for a person;
 *  `restart` says the change takes effect the next time the app starts. */
export type Saved = { ok: true; restart?: boolean } | { ok: false; error: string }

export type DateOrder = 'auto' | 'mdy' | 'dmy'

/** Whether Arena's log says Detailed Logs are on; `unknown` when the shell
 *  could not tell. */
export type DetailedLogs = 'enabled' | 'disabled' | 'unknown'

export type ShellSettings = {
  sources: {
    /** `found`: the shell found the log where the game writes it, and
     *  nobody chose the path. `detailedLogs` is read-only. */
    arenaLog: { path: string | null; found: boolean; detailedLogs: DetailedLogs }
    dateOrder: DateOrder
    mtgoHandle: string | null
    mtgoDir: string | null
    /** The folder of MTGO `.dek` exports, `null` when unset. */
    mtgoDeckDir: string | null
    /** The folder the shell found Magic Online writing to (Windows only),
     *  else `null`. Read-only. */
    mtgoFound: string | null
    dataDir: string
  }
  writing: {
    /** Whether a key is set. The key itself never reaches the page. */
    claudeKey: boolean
    topdeckKey: boolean
    model: string
    models: { value: string; label: string }[]
  }
  backup: {
    dir: string
    /** How many copies are kept; the oldest goes when a new one is made. */
    keep: number
    /** The last backup tried: when, whether it worked, and its size in
     *  bytes when the shell knows it. `null` when none has been tried. */
    last: { at: string; ok: boolean; bytes: number | null } | null
    /** How many backups the folder holds now. */
    inFolder: number
  }
}

export type KeyName = 'claude' | 'topdeck'

/** Where the shell's own update stands. `checkedAt` is ISO, UTC. */
export type UpdateStatus =
  | { state: 'unavailable'; reason: 'store' | 'development' | 'unsupported' }
  | { state: 'idle' }
  | { state: 'checking' }
  | { state: 'current'; checkedAt: string }
  | { state: 'downloading'; version: string }
  | { state: 'ready'; version: string }
  | { state: 'failed'; checkedAt: string }

/** One `cards --progress` event, bytes read of the total (null when unknown). */
export type FirstDataProgress =
  | { stage: 'download'; done: number; total: number | null }
  | { stage: 'save' }

/** Where `cards --scryfall` stands, as the shell runs it. `line` is the
 *  latest progress line, except one naming the database, which is never
 *  sent as `running`; `done`'s names a path and is never shown. `progress`
 *  is the latest `--progress` event the shell parsed (the page words it). */
export type FirstData =
  | { state: 'idle' }
  | { state: 'running'; line: string | null; progress?: FirstDataProgress }
  | { state: 'done'; line: string }
  | { state: 'failed'; error: string }

/** The language the shell is read in: the system's, or one chosen. */
export type LanguageChoice = 'system' | 'en' | 'pt-BR'

/** The shell's own preferences, which the server never reads. `platform` is
 *  Node's `process.platform`; `keepRunningOnClose` is Linux only. */
export type AppSettings = {
  startWithSystem: boolean
  keepRunningOnClose: boolean
  checkForUpdates: boolean
  diagnostic: boolean
  update: UpdateStatus
  /** Whether onboarding is finished; the shell opens `/welcome` until it is. */
  onboarded: boolean
  /** Whether onboarding's last step asks about starting with the system. */
  askAutostart: boolean
  /** Whether this copy can start at login: not the Linux tarball. */
  canAutostart: boolean
  /** The Microsoft Store build, which starts with Windows only through
   *  Windows' own Startup settings. */
  windowsStore: boolean
  /** Cards with rules text, from the shell's last read; `null` when unknown. */
  rulesText: number | null
  firstData: FirstData
  version: string
  platform: string
  /** The language preference (`shell.json`'s `language`). Absent from a
   *  shell that keeps none, and the page then keeps its own (`i18n.ts`). */
  language?: LanguageChoice
  /** Which clients the user plays (`shell.json`'s `plays`); absent from a
   *  shell that keeps none, and the page then reads both. */
  plays?: ('arena' | 'mtgo')[]
}

/** What the page can change of `AppSettings`. */
export type AppChange = Partial<
  Pick<AppSettings, 'startWithSystem' | 'keepRunningOnClose' | 'checkForUpdates' | 'diagnostic' | 'language' | 'plays'>
>

/** The shell's actions. `exportDiagnostics` answers `{ ok: true }` when the
 *  viewer cancels the shell's dialog too, so `ok` never means "exported". */
export type AppActions = {
  set(change: AppChange): Promise<Saved>
  checkForUpdates(): Promise<Saved>
  restartToUpdate(): Promise<Saved>
  showLogs(): Promise<Saved>
  exportDiagnostics(): Promise<Saved>
  showDataFolder(): Promise<Saved>
  /** Reads the config and the doctor again and publishes. */
  recheck(): Promise<Saved>
  /** Starts `cards --scryfall`; its progress arrives as `firstData`. */
  firstData(): Promise<Saved>
  finishOnboarding(): Promise<Saved>
}

/** What a change event and `initial` carry: the settings and the app part. */
export type BridgeSettings = ShellSettings & { app: AppSettings }

/** The shell's own part. Absent where the shell offers none (the reference
 *  page's sample shells), and the page then draws no App section. */
export type ShellApp = { settings: AppSettings } & AppActions

export type Shell = {
  settings: ShellSettings
  app?: ShellApp
  /** Never carries a key: a key is set by `setKey` alone. */
  save(change: DeepPartial<ShellSettings>): Promise<Saved>
  /** `null` removes the key. */
  setKey(which: KeyName, key: string | null): Promise<Saved>
  pickFolder(): Promise<string | null>
  pickFile(): Promise<string | null>
  backUpNow(): Promise<Saved>
  /** Takes effect the next time the app starts. */
  restoreFrom(path: string): Promise<Saved>
}

/** `window.senseiTopShell`, as the preload script exposes it. */
export type RawShell = Omit<Shell, 'settings' | 'app'> & {
  /** Read once by the preload script; `null` when the shell could not read them. */
  initial: BridgeSettings | null
  app: AppActions
  /** Calls `listener` after any change; returns a function that stops it. */
  onChange(listener: (settings: BridgeSettings) => void): () => void
}

/** The settings a shell holds as the page's `Shell`. */
export function shellFrom(raw: RawShell, settings: BridgeSettings): Shell {
  const { app, ...rest } = settings
  const { initial: _initial, app: actions, onChange: _onChange, ...functions } = raw
  void _initial
  void _onChange
  return { ...functions, settings: rest, app: { settings: app, ...actions } }
}

/** One shell's settings held for `useSyncExternalStore`: `null` until the
 *  shell has settings (its `initial` was `null`), then the `Shell`, which
 *  changes identity only when a change event arrives. It listens to the
 *  shell from the moment it is made and never stops, so an event published
 *  while no page is listening (a backup that ends after the person left
 *  Settings) is in the next snapshot. The dashboard makes its store at
 *  start (`startShellStore`), not at the first `useShell()`. `subscribe`
 *  manages React's listeners alone. */
export function shellStore(raw: RawShell | undefined): {
  subscribe(listener: () => void): () => void
  snapshot(): Shell | null
} {
  let current: Shell | null = raw && raw.initial ? shellFrom(raw, raw.initial) : null
  const listeners = new Set<() => void>()
  raw?.onChange((settings) => {
    current = shellFrom(raw, settings)
    for (const each of [...listeners]) each()
  })
  return {
    subscribe(listener) {
      listeners.add(listener)
      return () => void listeners.delete(listener)
    },
    snapshot: () => current,
  }
}

/** `window.senseiTopShell`, or `undefined` in a browser. The only place
 *  that names the global. */
export function readShellGlobal(): RawShell | undefined {
  return (globalThis as { senseiTopShell?: RawShell }).senseiTopShell
}

let held: { raw: RawShell | undefined; store: ReturnType<typeof shellStore> } | null = null

function storeOfGlobal() {
  const raw = readShellGlobal()
  if (!held || held.raw !== raw) held = { raw, store: shellStore(raw) }
  return held.store
}

/** Makes the dashboard's store now, so it hears the shell's change events
 *  from app start and not from the first page that reads the shell. Runs
 *  when this module loads, before the first render. */
export function startShellStore() {
  return storeOfGlobal()
}

startShellStore()

/** The shell the dashboard runs in, kept current by its change events from
 *  the start (`startShellStore`), not from this hook's first call. A
 *  browser has none, and gets `null`, as does a shell with no settings yet. */
export function useShell(): Shell | null {
  const store = storeOfGlobal()
  return useSyncExternalStore(store.subscribe, store.snapshot, store.snapshot)
}
