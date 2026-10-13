import { useSyncExternalStore } from 'react'

/**
 * What a desktop shell hands the dashboard: its settings, and the functions
 * that change them. The Electron shell in `desktop/` fills `useShell()`
 * through `window.senseiTopShell`, set by its preload script; a browser has
 * none, so here it answers `null` and every page draws what the API alone
 * can say. A component takes the parts it shows as props and never reads
 * this module's hook itself, so a change of the shell's shape is a change
 * of one mapping, in the page that calls `useShell()`.
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
  /** Sharing finished drafts; `null` where the app offers none, and the
   *  page then says nothing of it. */
  sharing: Sharing | null
}

/** Sharing finished drafts as the shell sees it. `on` is only ever turned
 *  by the viewer; `installation` is this installation's random id; `sent`
 *  counts the drafts sent under it. `lastDraft` is the newest finished
 *  draft's id, `null` before there is one. */
export type Sharing = { on: boolean; installation: string; sent: number; lastDraft: string | null }

/** One draft's place in sharing: never shared, waiting for its games to
 *  end, shared (`at` is when), or removed from the server by the viewer.
 *  `at` is `null` where it is not known or means nothing. */
export type SharedDraft = { state: 'not-shared' | 'waiting' | 'shared' | 'removed'; at: string | null }

/** What one draft sends, as the shell reads it, with cards by name where
 *  the payload holds Arena's numbers. Each `label` and `value` is text the
 *  shell wrote. A part the shell does not know is `null`, or left out of
 *  its list. */
export type DraftPayload = {
  /** The installation, the version, the system, the ratings' date. */
  about: { label: string; value: string }[]
  /** The event, the set, the hours it started and ended. */
  draft: { label: string; value: string }[]
  /** `from` is the pack the card was taken from, the taken card among them. */
  picks: { pack: number; pick: number; taken: string | null; from: string[] }[]
  deck: { main: string[]; sideboard: string[] } | null
  games: { result: string; onThePlay: boolean | null; turns: number | null; against: string | null }[]
  record: string | null
}

/** Deleting what was sent: how many drafts the server deleted, 0 when it
 *  held none. */
export type Deleted = { ok: true; count: number } | { ok: false; error: string }

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
  /** Cards with rules text, from the shell's last read; `null` when unknown. */
  rulesText: number | null
  firstData: FirstData
  version: string
  platform: string
  /** The language preference (`shell.json`'s `language`). Absent from a
   *  shell that keeps none, and the page then keeps its own (`i18n.ts`). */
  language?: LanguageChoice
}

/** What the page can change of `AppSettings`. */
export type AppChange = Partial<
  Pick<AppSettings, 'startWithSystem' | 'keepRunningOnClose' | 'checkForUpdates' | 'diagnostic' | 'language'>
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
  /** Whether finished drafts are shared; called by the viewer's press alone. */
  setSharing(on: boolean): Promise<Saved>
  /** What the draft sends, or would; `null` when the shell has none. */
  payloadOf(draftId: string): Promise<DraftPayload | null>
  sharedState(draftId: string): Promise<SharedDraft>
  /** Removes one shared draft from the server. */
  unshare(draftId: string): Promise<Saved>
  /** Deletes every draft sent under this installation's id. */
  deleteContributions(): Promise<Deleted>
  /** A new random id; what was sent under the old one stays on the server. */
  newInstallation(): Promise<Saved>
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
