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

/** Why a session does not outlive the launch: no system keyring (Linux), or
 *  no encryption at all. */
export type AccountPersistence = { kept: true } | { kept: false; reason: 'noKeyring' | 'noEncryption' }

export type AccountStatus = {
  signedIn: boolean
  userId: string | null
  email: string | null
  /** The provider the session was signed in with, as Supabase names it. */
  provider: string | null
  persistence: AccountPersistence
}

/** The account's profile, as the shell reads it from the cloud. `unknown`: it
 *  could not be read (do not ask the consent questions again); `none`: no
 *  answers given yet. */
export type ProfileState =
  | { state: 'unknown' }
  | { state: 'none' }
  | {
      state: 'read'
      ageConfirmedAt: string
      consentSync: boolean
      consentErrors: boolean
      consentCoachHistory: boolean
      /** The privacy policy's version the answers were given under. */
      consentVersion: string
      consentedAt: string
    }

/** `localApi`: the local server did not answer; `cloud`: the account's
 *  project did not; `disk`: the sync state could not be written. */
export type SyncError = 'localApi' | 'cloud' | 'disk'

/** What the page is shown of the cloud backup. */
export type SyncStatus = {
  running: boolean
  lastSyncAt: string | null
  /** Matches this install has backed up for the signed-in account. */
  backedUp: number
  /** Why the last run stopped; `null` after one that finished. */
  lastError: SyncError | null
}

/** What a signed-in account adds once the shell's account module runs. */
export type AccountDetails = { profile: ProfileState; sync: SyncStatus }

/** `available: false`: this build has no account (no Supabase project). */
export type AccountState = { available: false } | ({ available: true } & AccountStatus & Partial<AccountDetails>)

export type AccountProvider = 'google' | 'discord'

export type SignInError =
  | 'auth.error.unverifiedEmail'
  | 'auth.error.cancelled'
  | 'auth.error.timeout'
  | 'auth.error.noPort'
  | 'auth.error.failed'

/** `message` is in the shell's language, ready to show. */
export type SignInReply = { ok: true; account: AccountStatus } | { ok: false; error: SignInError; message: string }

/** `unavailable`: no account in this build. `signedOut`: the action needs a
 *  sign-in. `invalid`: malformed input. `ageNotConfirmed`: a first profile
 *  needs the age confirmation. `failed`: the cloud or the disk refused it. */
export type AccountError = 'unavailable' | 'signedOut' | 'invalid' | 'ageNotConfirmed' | 'failed'

/** An account action's answer. `cancelled`: the export's save dialog was
 *  closed. `deleted`: how many rows a delete removed. */
export type AccountReply = { ok: true; cancelled?: boolean; deleted?: number } | { ok: false; error: AccountError }

/** The consent screen's answers. */
export type ProfileChange = {
  consentSync: boolean
  consentErrors: boolean
  consentCoachHistory: boolean
  /** The privacy policy's version the answers were given under. */
  policyVersion: string
  /** Required by the first write, ignored after it. */
  ageConfirmed?: boolean
}

/** The account calls; resolves once the sign-in ended (up to five minutes). */
export type AccountActions = {
  status(): Promise<AccountState>
  signIn(provider: AccountProvider): Promise<SignInReply>
  signOut(): Promise<Saved>
  setProfile(change: ProfileChange): Promise<AccountReply>
  /** Opens the shell's save dialog; `cancelled` when it is closed. */
  exportData(): Promise<AccountReply>
  /** Also turns the backup off, and a failed delete leaves it off. */
  deleteCloudHistory(): Promise<AccountReply>
  /** Needs a signed-in user, not a profile. */
  deleteAccount(): Promise<AccountReply>
  /** Reads a profile that could not be read again; `ok` once it is read. */
  readProfileAgain(): Promise<AccountReply>
}

/** The stored answer to "Help build the stats", and what it was given to. */
export type Contribute = {
  yes: boolean
  /** The privacy policy's version the answer was given under. */
  policyVersion: string
  answeredAt: string
  ageConfirmed: boolean
}

/** What the page sends with "Help build the stats"; `off` stops any upload at once. */
export type ContribAnswer = { yes: boolean; policyVersion: string; ageConfirmed: boolean }

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
  /** Whether AI features are on. `null`: undecided, a fresh install that
   *  `/welcome` will ask; it reads as off. */
  aiFeatures: boolean | null
  /** Whether this build can upload contributed games; read-only. False hides the question, the one-time page and the Settings card. */
  canContribute: boolean
  /** Whether the one-time "Help build the stats" page was shown; set it to true through `app.set`; only `true` is stored. */
  contribAsked: boolean
  /** Whether the user dismissed the offer to sign in; set it to true through `app.set`; only `true` is stored. */
  signInDismissed: boolean
  /** The stored "Help build the stats" answer; `null` while unanswered, which sends nothing. */
  contribute: Contribute | null
  /** The account; a change arrives with the rest of the settings. */
  account: AccountState
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
> & { aiFeatures?: boolean; contribAsked?: true; signInDismissed?: true }

/** The shell's actions. `exportDiagnostics` answers `{ ok: true }` when the
 *  viewer cancels the shell's dialog too, so `ok` never means "exported". */
export type AppActions = {
  set(change: AppChange): Promise<Saved>
  checkForUpdates(): Promise<Saved>
  restartToUpdate(): Promise<Saved>
  /** Restart now: the shell stops its server as a quit does, then starts again. */
  relaunch(): Promise<Saved>
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
export type ShellApp = { settings: AppSettings } & AppActions & { account: AccountActions }

/** A renderer error as the page hands it to the shell (the shell drops it
 *  unless the user said yes to error reports). */
export type RendererErrorReport = { name: string; message: string; stack: string | null }

/** What `reportProblem` answers; the shell names the outcome, the page words it. */
export type ReportOutcome = 'sent' | 'sent-without-log' | 'unavailable' | 'invalid' | 'failed'

/** The error-report calls. Absent from a shell that has none. */
export type ShellReports = {
  /** `true` when the shell captured it. */
  reportError(error: RendererErrorReport): Promise<boolean>
  /** Sends one report whatever the error-reports choice; the caller has asked the transfer consent. */
  reportProblem(report: { text: string; attachLog: boolean }): Promise<ReportOutcome>
  /** Calls `listener` when the shell's tray asked for the report dialog; returns a function that stops it. */
  onReportProblem(listener: () => void): () => void
}

export type Shell = Partial<ShellReports> & {
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
  /** The answer to "Help build the stats"; a yes needs `ageConfirmed: true`. */
  contribSet(answer: ContribAnswer): Promise<Saved>
}

/** `window.senseiTopShell`, as the preload script exposes it. */
export type RawShell = Omit<Shell, 'settings' | 'app' | keyof ShellReports> & Partial<ShellReports> & {
  /** Read once by the preload script; `null` when the shell could not read them. */
  initial: BridgeSettings | null
  app: AppActions
  account: AccountActions
  /** Calls `listener` after any change; returns a function that stops it. */
  onChange(listener: (settings: BridgeSettings) => void): () => void
}

/** The settings a shell holds as the page's `Shell`. */
export function shellFrom(raw: RawShell, settings: BridgeSettings): Shell {
  const { app, ...rest } = settings
  const { initial: _initial, app: actions, account, onChange: _onChange, ...functions } = raw
  void _initial
  void _onChange
  return { ...functions, settings: rest, app: { settings: app, ...actions, account } }
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
