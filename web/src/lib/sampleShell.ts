/**
 * A shell made up for the reference page, `/design/surfaces`, and for
 * nothing else: every path, name, model, price and day in it is invented,
 * and it is the one file in the dashboard that holds a price. Its state
 * lives in the page's memory, so a save shows on the page and is gone on
 * a reload.
 */
import { useState } from 'react'
import type {
  Allowance,
  DeepPartial,
  Deleted,
  Device,
  DraftPayload,
  Offer,
  Plan,
  Saved,
  SharedDraft,
  Sharing,
  Shell,
  ShellSettings,
  Sync,
  SyncPause,
  SyncSetUp,
} from '../bridge'
import type { WritingStatusAnswer } from '../components/settings/WritingSection'

export type SampleId =
  | 'no-shell'
  | 'no-shell-no-key'
  | 'nothing'
  | 'everything'
  | 'fails'
  | 'restart'
  | 'backup-failed'
  | 'first-backup-failed'
  | 'plan-none'
  | 'plan-trial'
  | 'plan-trial-cancelled'
  | 'plan-pro'
  | 'plan-pro-used'
  | 'plan-payment-failed'
  | 'plan-ended'
  | 'sync-no-plan'
  | 'sync-off'
  | 'sync-on'
  | 'sync-full'
  | 'sync-plan-ended'
  | 'sync-offline'
  | 'sync-locked'
  | 'sharing-off'
  | 'sharing-on'
  | 'sharing-none'

export const SAMPLE_OPTIONS: { value: SampleId; label: string }[] = [
  { value: 'no-shell', label: 'No shell' },
  { value: 'no-shell-no-key', label: 'No shell, no key' },
  { value: 'nothing', label: 'Nothing set' },
  { value: 'everything', label: 'Everything set' },
  { value: 'fails', label: 'A save fails' },
  { value: 'restart', label: 'A restart is needed' },
  { value: 'backup-failed', label: 'The last backup failed' },
  { value: 'first-backup-failed', label: 'The first backup failed' },
  { value: 'plan-none', label: 'No plan' },
  { value: 'plan-trial', label: 'On trial' },
  { value: 'plan-trial-cancelled', label: 'On trial, cancelled' },
  { value: 'plan-pro', label: 'Pro' },
  { value: 'plan-pro-used', label: 'Pro, allowance used' },
  { value: 'plan-payment-failed', label: 'Payment failed' },
  { value: 'plan-ended', label: 'Plan ended' },
  { value: 'sync-no-plan', label: 'Sync, no plan' },
  { value: 'sync-off', label: 'Sync, off' },
  { value: 'sync-on', label: 'Sync, on' },
  { value: 'sync-full', label: 'Sync, storage full' },
  { value: 'sync-plan-ended', label: 'Sync, plan ended' },
  { value: 'sync-offline', label: 'Sync, offline' },
  { value: 'sync-locked', label: 'Sync, locked' },
  { value: 'sharing-off', label: 'Sharing, off' },
  { value: 'sharing-on', label: 'Sharing, on' },
  { value: 'sharing-none', label: 'Sharing, no draft yet' },
]

const MODELS = [
  { value: 'opus-5.5', label: 'Opus 5.5' },
  { value: 'sonnet-5', label: 'Sonnet 5' },
  { value: 'fable-5.1', label: 'Fable 5.1' },
]

const BACKUP_DIR = '/home/sample/sensei-top/backups'

/** 41.3 MB, the size of every invented backup. */
const BACKUP_BYTES = 41_300_000

/** Two hours before the page opened: the invented last backup. */
const LAST_BACKUP_AT = new Date(Date.now() - 2 * 3_600_000).toISOString()

/* Sharing's samples: an invented installation, fourteen drafts sent under
 * it, and one finished draft whose payload names no real card, set or
 * event. */

const INSTALLATION = '00000000-sample-0000-0000-000000000000'
const NEW_INSTALLATION = '00000000-sample-0000-0000-000000000001'
const SAMPLE_DRAFT_ID = 'sample-draft'
const DRAFTS_SENT = 14

/** Three hours before the page opened: when the invented draft was sent. */
export const SAMPLE_SENT_AT = new Date(Date.now() - 3 * 3_600_000).toISOString()

const SHARING_OFF: Sharing = { on: false, installation: INSTALLATION, sent: DRAFTS_SENT, lastDraft: SAMPLE_DRAFT_ID }

const NUMBER_WORDS = [
  '',
  'One',
  'Two',
  'Three',
  'Four',
  'Five',
  'Six',
  'Seven',
  'Eight',
  'Nine',
  'Ten',
  'Eleven',
  'Twelve',
  'Thirteen',
  'Fourteen',
  'Fifteen',
  'Sixteen',
  'Seventeen',
  'Eighteen',
  'Nineteen',
]
const TENS_WORDS = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']

/** "Sample Card One", "Sample Card Twenty-Two": the `n`th invented card, 1 to 99. */
function sampleCard(n: number): string {
  const word = n < 20 ? NUMBER_WORDS[n] : `${TENS_WORDS[Math.floor(n / 10)]}${n % 10 ? `-${NUMBER_WORDS[n % 10]}` : ''}`
  return `Sample Card ${word}`
}

/** Three packs of fourteen: each pick takes the next invented card, from a
 *  pack one card smaller than the pick before. The card of pack 2's ninth
 *  pick is not known. */
function samplePicks(): DraftPayload['picks'] {
  const picks: DraftPayload['picks'] = []
  let taken = 0
  for (let pack = 1; pack <= 3; pack++) {
    for (let pick = 1; pick <= 14; pick++) {
      const size = 15 - pick
      const known = !(pack === 2 && pick === 9)
      const card = known ? sampleCard(++taken) : null
      // The rest of the pack is one invented card over and over: only how
      // many there are is drawn.
      const from = Array.from({ length: size }, () => sampleCard(99))
      if (card !== null) from[0] = card
      picks.push({ pack, pick, taken: card, from })
    }
  }
  return picks
}

const PICKS = samplePicks()
const TAKEN = PICKS.flatMap((pick) => (pick.taken === null ? [] : [pick.taken]))

/** The invented draft's payload: its 41 known cards, 23 of them in the
 *  deck with seventeen invented lands, and eight games that make the
 *  record. */
export const SAMPLE_PAYLOAD: DraftPayload = {
  about: [
    { label: 'Installation', value: INSTALLATION },
    { label: 'Version', value: '0.0.0-sample' },
    { label: 'System', value: 'Sample OS' },
    { label: 'Ratings from', value: '2026-01-14' },
  ],
  draft: [
    { label: 'Event', value: 'Quick Draft' },
    { label: 'Set', value: 'SMP' },
    { label: 'Started', value: '2026-01-15 19:00' },
    { label: 'Ended', value: '2026-01-15 21:00' },
  ],
  picks: PICKS,
  deck: {
    main: [
      ...TAKEN.slice(0, 23),
      ...Array.from({ length: 9 }, () => 'Sample Land One'),
      ...Array.from({ length: 8 }, () => 'Sample Land Two'),
    ],
    sideboard: TAKEN.slice(23),
  },
  games: [
    { result: 'Win', onThePlay: true, turns: 9, against: 'white and red' },
    { result: 'Win', onThePlay: false, turns: 11, against: 'blue and black' },
    { result: 'Loss', onThePlay: true, turns: 7, against: 'green' },
    { result: 'Win', onThePlay: null, turns: 10, against: 'black and green' },
    { result: 'Loss', onThePlay: false, turns: 12, against: null },
    { result: 'Win', onThePlay: true, turns: null, against: 'white and blue' },
    { result: 'Loss', onThePlay: false, turns: 8, against: 'red and green' },
    { result: 'Win', onThePlay: true, turns: 13, against: 'blue and red' },
  ],
  record: '5 wins, 3 losses',
}

/** The invented draft's place in sharing: shared three hours ago in
 *  "Sharing, on", and never shared in any other sample. */
export function sampleSharedDraft(sample: SampleId): SharedDraft {
  return sample === 'sharing-on' ? { state: 'shared', at: SAMPLE_SENT_AT } : { state: 'not-shared', at: null }
}

/** Undoing the invented shared draft, after 400 ms: refused with no
 *  sentence of the shell's own in "A save fails", done in any other. */
export function sampleUnshare(sample: SampleId): Promise<Saved> {
  return afterAWhile(() => (sample === 'fails' ? { ok: false, error: '' } : { ok: true }))
}

const NOTHING_SET: ShellSettings = {
  sources: {
    arenaLog: { path: null, found: false },
    dateOrder: 'auto',
    mtgoHandle: null,
    mtgoDir: null,
    dataDir: '/home/sample/sensei-top',
  },
  writing: { claudeKey: false, topdeckKey: false, model: MODELS[0].value, models: MODELS },
  backup: { dir: BACKUP_DIR, keep: 7, last: null, inFolder: 0 },
  plan: { state: 'not-offered' },
  devices: [],
  deviceLimit: 2,
  sync: { state: 'off' },
  sharing: null,
}

const EVERYTHING_SET: ShellSettings = {
  sources: {
    arenaLog: { path: '/games/arena/Player.log', found: true },
    dateOrder: 'mdy',
    mtgoHandle: 'Sample Player',
    mtgoDir: '/games/mtgo/logs',
    dataDir: '/home/sample/sensei-top',
  },
  writing: { claudeKey: true, topdeckKey: true, model: MODELS[0].value, models: MODELS },
  backup: { dir: BACKUP_DIR, keep: 14, last: { at: LAST_BACKUP_AT, ok: true, bytes: BACKUP_BYTES }, inFolder: 14 },
  plan: { state: 'not-offered' },
  devices: [],
  deviceLimit: 2,
  sync: { state: 'off' },
  sharing: SHARING_OFF,
}

const BACKUP_FAILED: ShellSettings = {
  ...EVERYTHING_SET,
  backup: { ...EVERYTHING_SET.backup, last: { at: LAST_BACKUP_AT, ok: false, bytes: null } },
}

/** The only backup tried failed, and the folder holds none. */
const FIRST_BACKUP_FAILED: ShellSettings = {
  ...EVERYTHING_SET,
  backup: { ...EVERYTHING_SET.backup, last: { at: LAST_BACKUP_AT, ok: false, bytes: null }, inFolder: 0 },
}

/* The plan's samples. Every price is invented, and every day is counted
 * from the moment the page opened, so "four days left" is true whenever
 * the page is read. */

const OPENED = new Date()

/** Noon of the day `days` after the page opened, in the viewer's zone, so
 *  a change of the clock between cannot move it to another day. */
function dayFromOpened(days: number): string {
  return new Date(OPENED.getFullYear(), OPENED.getMonth(), OPENED.getDate() + days, 12).toISOString()
}

const BY_MONTH = 'US$10'
const BY_YEAR = 'US$84'

const OFFER: Offer = { byMonth: BY_MONTH, byYear: BY_YEAR, trialDays: 7 }

const TRIAL_ENDS = dayFromOpened(4)
const RENEWS_ON = dayFromOpened(19)

const PRO_ALLOWANCE: Allowance = {
  used: 0.38,
  startsAgain: RENEWS_ON,
  left: [
    { kind: 'coach', about: 2 },
    { kind: 'guide', about: 3 },
    { kind: 'leaks', about: 3 },
    { kind: 'match', about: 25 },
  ],
}

const TRIAL_ALLOWANCE: Allowance = {
  used: 0.2,
  startsAgain: TRIAL_ENDS,
  left: [
    { kind: 'coach', about: 1 },
    { kind: 'guide', about: 1 },
    { kind: 'leaks', about: 1 },
    { kind: 'match', about: 8 },
  ],
}

const USED_ALLOWANCE: Allowance = {
  used: 1,
  startsAgain: RENEWS_ON,
  left: [
    { kind: 'coach', about: 0 },
    { kind: 'guide', about: 0 },
    { kind: 'leaks', about: 0 },
    { kind: 'match', about: 0 },
  ],
}

const PRO: Plan = {
  state: 'active',
  every: 'month',
  renews: { on: RENEWS_ON, amount: BY_MONTH },
  until: RENEWS_ON,
  allowance: PRO_ALLOWANCE,
}

const DEVICES: Device[] = [
  { id: 'desk', name: 'Desk', here: true, seen: OPENED.toISOString() },
  { id: 'laptop', name: 'Laptop', here: false, seen: new Date(OPENED.getTime() - 3 * 86_400_000).toISOString() },
]

/** `EVERYTHING_SET` with a plan, the invented computers and cloud sync:
 *  by default offered to a viewer with no plan, and not set up on one. */
function withPlan(plan: Plan, sync?: Sync): ShellSettings {
  const plain: Sync = plan.state === 'none' || plan.state === 'ended' ? { state: 'no-plan' } : { state: 'off' }
  return { ...EVERYTHING_SET, plan, devices: DEVICES, deviceLimit: 2, sync: sync ?? plain }
}

/* Cloud sync's samples: 412 MB of a 2 GB quota, a last sync twelve minutes
 * before the page opened, and a lapsed plan's copy kept sixty days after. */

const SYNC_QUOTA = 2_000_000_000
const SYNC_BYTES = 412_000_000
const LAST_SYNC_AT = new Date(OPENED.getTime() - 12 * 60_000).toISOString()
const KEPT_UNTIL = dayFromOpened(60)
const RECOVERY_CODE = 'SAMPLE-7Q4K-M2XD-91TV-HB3C'

/** What opens the locked sample's copy; anything else is refused. */
const UNLOCK_PHRASE = 'sample passphrase'

const SYNC_ON: Sync = { state: 'on', enabled: true, last: LAST_SYNC_AT, bytes: SYNC_BYTES, quota: SYNC_QUOTA }

/** Sync paused for `why`, over `bytes` stored. */
function syncPaused(why: SyncPause, bytes: number, keptUntil: string | null = null): Sync {
  return { state: 'paused', why, enabled: true, last: LAST_SYNC_AT, bytes, quota: SYNC_QUOTA, keptUntil }
}

const PLAN_ENDED: Plan = { state: 'ended', on: dayFromOpened(-12), offer: { ...OFFER, trialDays: null } }

const INITIAL: Partial<Record<SampleId, ShellSettings>> = {
  nothing: NOTHING_SET,
  'backup-failed': BACKUP_FAILED,
  'first-backup-failed': FIRST_BACKUP_FAILED,
  'plan-none': withPlan({ state: 'none', offer: OFFER }),
  'plan-trial': withPlan({
    state: 'trial',
    ends: TRIAL_ENDS,
    then: { on: TRIAL_ENDS, amount: BY_MONTH },
    allowance: TRIAL_ALLOWANCE,
  }),
  'plan-trial-cancelled': withPlan({ state: 'trial', ends: TRIAL_ENDS, then: null, allowance: TRIAL_ALLOWANCE }),
  'plan-pro': withPlan(PRO),
  'plan-pro-used': withPlan({
    state: 'active',
    every: 'year',
    renews: { on: dayFromOpened(200), amount: BY_YEAR },
    until: dayFromOpened(200),
    allowance: USED_ALLOWANCE,
  }),
  'plan-payment-failed': withPlan({ state: 'payment-failed', until: dayFromOpened(6), allowance: PRO_ALLOWANCE }),
  'plan-ended': withPlan(PLAN_ENDED),
  'sync-no-plan': withPlan({ state: 'none', offer: OFFER }),
  'sync-off': withPlan(PRO),
  'sync-on': withPlan(PRO, SYNC_ON),
  'sync-full': withPlan(PRO, syncPaused('quota', SYNC_QUOTA)),
  'sync-plan-ended': withPlan(PLAN_ENDED, syncPaused('plan', SYNC_BYTES, KEPT_UNTIL)),
  'sync-offline': withPlan(PRO, syncPaused('offline', SYNC_BYTES)),
  'sync-locked': withPlan(PRO, { state: 'locked' }),
  'sharing-on': { ...EVERYTHING_SET, sharing: { ...SHARING_OFF, on: true } },
  'sharing-none': { ...EVERYTHING_SET, sharing: { ...SHARING_OFF, sent: 0, lastDraft: null } },
}

const CHOSEN_FOLDER = '/games/chosen'
const CHOSEN_FILE = '/home/sample/backups/matches-2026-01-15.db.backup'
const ANSWER_MS = 400

/** What the API would say of writing, for the two samples with no shell.
 *  The model is its label, as an id that came with no list to name it. */
export function sampleWriting(sample: SampleId): WritingStatusAnswer {
  if (sample === 'no-shell-no-key') return { configured: false, model: null }
  return { configured: true, model: MODELS[0].label }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** `base` with `change` laid over it, object by object. */
function merged<T>(base: T, change: DeepPartial<T>): T {
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) }
  for (const [field, value] of Object.entries(change as Record<string, unknown>)) {
    if (value === undefined) continue
    const under = out[field]
    out[field] = isRecord(value) && isRecord(under) ? merged(under, value) : value
  }
  return out as T
}

function afterAWhile(answer: () => Saved): Promise<Saved> {
  return afterAWhileWith(answer)
}

function afterAWhileWith<T>(answer: () => T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(answer()), ANSWER_MS))
}

/** The sample's shell, or `null` for the two samples with no shell. Its
 *  state starts again whenever the component holding it does, so the page
 *  keys that component by the sample. `save`, `setKey`, `backUpNow`,
 *  `restoreFrom` and the plan's functions answer after 400 ms;
 *  `pickFolder` answers an invented folder and `pickFile` an invented
 *  backup file. A backup made here is one more in the folder, up to the
 *  count kept; a restore changes nothing on the page. A key activated here
 *  starts the plan, but on "Plan ended", where it is refused; the checkout
 *  and the plan's page open nothing; a computer removed leaves the list.
 *  Cloud sync's functions answer after 400 ms too: a setup answers the
 *  invented recovery code and turns sync on, the locked copy opens with
 *  "sample passphrase" alone, "Sync now" makes the last sync now on a sync
 *  that is not paused and fails on one paused offline, and a deletion
 *  leaves sync not set up. Sharing's answer after 400 ms as well: the
 *  switch turns only when pressed, the invented draft's payload is the
 *  one answered, a deletion answers the drafts sent under this id and
 *  leaves none (so none after a first deletion or a new id) and, in "A
 *  save fails", is refused with no sentence of the shell's own. */
export function useSampleShell(sample: SampleId): Shell | null {
  const [settings, setSettings] = useState<ShellSettings>(() => INITIAL[sample] ?? EVERYTHING_SET)
  if (sample === 'no-shell' || sample === 'no-shell-no-key') return null

  const answer = (): Saved =>
    sample === 'fails'
      ? { ok: false, error: 'The folder could not be written to.' }
      : sample === 'restart'
        ? { ok: true, restart: true }
        : { ok: true }

  return {
    settings,
    save: (change) =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          setSettings((current) => {
            const next = merged(current, change)
            // A path the viewer gave is one nobody found.
            return change.sources?.arenaLog?.path === undefined
              ? next
              : merged(next, { sources: { arenaLog: { found: false } } })
          })
        }
        return saved
      }),
    setKey: (which, key) =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          const set = key !== null
          setSettings((current) =>
            merged(current, { writing: which === 'claude' ? { claudeKey: set } : { topdeckKey: set } }),
          )
        }
        return saved
      }),
    pickFolder: () => Promise.resolve(CHOSEN_FOLDER),
    pickFile: () => Promise.resolve(CHOSEN_FILE),
    backUpNow: () =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          const at = new Date().toISOString()
          setSettings((current) =>
            merged(current, {
              backup: {
                last: { at, ok: true, bytes: BACKUP_BYTES },
                inFolder: Math.min(current.backup.inFolder + 1, current.backup.keep),
              },
            }),
          )
        }
        return saved
      }),
    restoreFrom: () => afterAWhile(answer),
    activate: () =>
      afterAWhile(() => {
        // A plan that ended shows a key refused, with no sentence of the
        // shell's own; any other sample takes the key and starts the plan.
        if (sample === 'plan-ended') return { ok: false, error: '' }
        const saved = answer()
        if (saved.ok) {
          setSettings((current) => ({ ...current, plan: PRO, devices: DEVICES, sync: syncWithPlan(current.sync) }))
        }
        return saved
      }),
    startTrial: () => afterAWhile(answer),
    managePlan: () => afterAWhile(answer),
    removeDevice: (id) =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          setSettings((current) => ({ ...current, devices: current.devices.filter((device) => device.id !== id) }))
        }
        return saved
      }),
    setUpSync: () =>
      afterAWhileWith((): SyncSetUp => {
        const saved = answer()
        if (!saved.ok) return saved
        setSettings((current) => ({ ...current, sync: { ...SYNC_ON, last: new Date().toISOString() } }))
        return { ok: true, recovery: RECOVERY_CODE }
      }),
    unlockSync: (passphraseOrCode) =>
      afterAWhile(() => {
        // Refused with no sentence of the shell's own, so the card says its plain one.
        if (passphraseOrCode !== UNLOCK_PHRASE) return { ok: false, error: '' }
        setSettings((current) => ({ ...current, sync: { ...SYNC_ON, last: new Date().toISOString() } }))
        return { ok: true }
      }),
    setSync: (on) =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) {
          setSettings((current) =>
            current.sync.state === 'on' || current.sync.state === 'paused'
              ? { ...current, sync: { ...current.sync, enabled: on } }
              : current,
          )
        }
        return saved
      }),
    syncNow: () =>
      afterAWhile(() => {
        // Offline, a sync fails, with no sentence of the shell's own.
        if (settings.sync.state === 'paused' && settings.sync.why === 'offline') return { ok: false, error: '' }
        const saved = answer()
        if (saved.ok) {
          const last = new Date().toISOString()
          setSettings((current) =>
            current.sync.state === 'on' ? { ...current, sync: { ...current.sync, last } } : current,
          )
        }
        return saved
      }),
    deleteCloudData: () =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) setSettings((current) => ({ ...current, sync: { state: 'off' } }))
        return saved
      }),
    setSharing: (on) =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) setSharingPart((sharing) => ({ ...sharing, on }))
        return saved
      }),
    payloadOf: (draftId) => afterAWhileWith(() => (draftId === SAMPLE_DRAFT_ID ? SAMPLE_PAYLOAD : null)),
    sharedState: () => afterAWhileWith(() => sampleSharedDraft(sample)),
    unshare: () => sampleUnshare(sample),
    deleteContributions: () =>
      afterAWhileWith((): Deleted => {
        if (sample === 'fails') return { ok: false, error: '' }
        setSharingPart((sharing) => ({ ...sharing, sent: 0 }))
        return { ok: true, count: settings.sharing?.sent ?? 0 }
      }),
    newInstallation: () =>
      afterAWhile(() => {
        const saved = answer()
        if (saved.ok) setSharingPart((sharing) => ({ ...sharing, installation: NEW_INSTALLATION, sent: 0 }))
        return saved
      }),
  }

  /** Changes the sharing part of the settings, where there is one. */
  function setSharingPart(change: (sharing: Sharing) => Sharing) {
    setSettings((current) => (current.sharing ? { ...current, sharing: change(current.sharing) } : current))
  }
}

/** Cloud sync once a plan starts: offered becomes not set up, and a copy
 *  paused by the lapsed plan syncs again. */
function syncWithPlan(sync: Sync): Sync {
  if (sync.state === 'no-plan') return { state: 'off' }
  if (sync.state === 'paused' && sync.why === 'plan') {
    return { state: 'on', enabled: sync.enabled, last: sync.last, bytes: sync.bytes, quota: sync.quota }
  }
  return sync
}
