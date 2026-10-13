/**
 * A shell made up for the reference page, `/design/surfaces`, and for
 * nothing else: every path, name, model and day in it is invented. Its state
 * lives in the page's memory, so a save shows on the page and is gone on
 * a reload.
 */
import { useState } from 'react'
import type { DeepPartial, Deleted, DraftPayload, Saved, SharedDraft, Sharing, Shell, ShellSettings } from '../bridge'
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
    arenaLog: { path: null, found: false, detailedLogs: 'unknown' },
    dateOrder: 'auto',
    mtgoHandle: null,
    mtgoDir: null,
    mtgoFound: null,
    dataDir: '/home/sample/sensei-top',
  },
  writing: { claudeKey: false, topdeckKey: false, model: MODELS[0].value, models: MODELS },
  backup: { dir: BACKUP_DIR, keep: 7, last: null, inFolder: 0 },
  sharing: null,
}

const EVERYTHING_SET: ShellSettings = {
  sources: {
    arenaLog: { path: '/games/arena/Player.log', found: true, detailedLogs: 'enabled' },
    dateOrder: 'mdy',
    mtgoHandle: 'Sample Player',
    mtgoDir: '/games/mtgo/logs',
    mtgoFound: '/games/mtgo/logs',
    dataDir: '/home/sample/sensei-top',
  },
  writing: { claudeKey: true, topdeckKey: true, model: MODELS[0].value, models: MODELS },
  backup: { dir: BACKUP_DIR, keep: 14, last: { at: LAST_BACKUP_AT, ok: true, bytes: BACKUP_BYTES }, inFolder: 14 },
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

const INITIAL: Partial<Record<SampleId, ShellSettings>> = {
  nothing: NOTHING_SET,
  'backup-failed': BACKUP_FAILED,
  'first-backup-failed': FIRST_BACKUP_FAILED,
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
 *  keys that component by the sample. `save`, `setKey`, `backUpNow` and
 *  `restoreFrom` answer after 400 ms;
 *  `pickFolder` answers an invented folder and `pickFile` an invented
 *  backup file. A backup made here is one more in the folder, up to the
 *  count kept; a restore changes nothing on the page. Sharing's functions
 *  answer after 400 ms as well: the
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
