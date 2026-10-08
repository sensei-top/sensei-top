/**
 * What a desktop shell hands the dashboard: its settings, and the functions
 * that change them. The desktop shell fills `useShell()`; a browser has
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

export type ShellSettings = {
  sources: {
    /** `found`: the shell found the log where the game writes it, and
     *  nobody chose the path. */
    arenaLog: { path: string | null; found: boolean }
    dateOrder: DateOrder
    mtgoHandle: string | null
    mtgoDir: string | null
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

export type Shell = {
  settings: ShellSettings
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

/** The shell the dashboard runs in. The desktop shell fills it; a browser
 *  has none, and gets `null`. */
export function useShell(): Shell | null {
  return null
}
