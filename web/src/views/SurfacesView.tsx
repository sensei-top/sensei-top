/**
 * The second reference page, at `/design/surfaces`: Settings and a
 * report's card, drawn with a sample shell whose every path, name and model is
 * invented and whose saves are kept in memory alone. The "Sample" select
 * picks what the page is drawn with, the two samples with no shell among
 * them, and starts that sample's state again. Under Settings, what the
 * invented draft sends, as the sample's sharing says; then the two lines
 * sharing draws on a draft's page; then a report's card as each writer
 * draws it, over an invented prompt and report; last, the drawing of where
 * Arena keeps Detailed Logs, at the Arena step's size and the Home banner's.
 */
import { useEffect, useState } from 'react'
import type { AppSettings, Saved, Shell } from '../bridge'
import { GenerateCard } from '../components/GenerateCard'
import { DetailedLogsGuide } from '../components/onboarding/DetailedLogsGuide'
import { DraftReceipt } from '../components/sharing/DraftReceipt'
import { PayloadView } from '../components/sharing/PayloadView'
import { SharingNote } from '../components/sharing/SharingNote'
import { PageHeader, SectionLabel, Select, TextLink } from '../components/ui'
import {
  SAMPLE_OPTIONS,
  SAMPLE_PAYLOAD,
  SAMPLE_SENT_AT,
  sampleSharedDraft,
  sampleUnshare,
  sampleWriting,
  useSampleShell,
  type SampleId,
} from '../lib/sampleShell'
import type { Writer } from '../lib/writer'
import { SettingsView } from './SettingsView'

export default function SurfacesView() {
  const [sample, setSample] = useState<SampleId>('no-shell')
  return (
    <main className="mx-auto max-w-6xl space-y-10 px-4 py-8 sm:px-8 sm:py-12">
      <PageHeader
        title="Surfaces"
        lead="Settings and a report's card, drawn with invented values. Nothing here is saved anywhere."
        actions={
          <TextLink href="/design" className="inline-flex min-h-[44px] items-center">
            The design reference
          </TextLink>
        }
      />
      <Select
        label="Sample"
        placement="above"
        value={sample}
        options={SAMPLE_OPTIONS}
        onChange={(value) => setSample(value as SampleId)}
      />
      <SampleSettings key={sample} sample={sample} />
      <DraftPageSamples key={`draft-${sample}`} sample={sample} />
      <WritingSamples />
      <DetailedLogsSamples />
    </main>
  )
}

/** The section's anchor that Draft data's link scrolls to. */
const PAYLOAD_ID = 'what-a-draft-sends'

/** Settings as the sample draws them, then what the invented draft sends,
 *  with sharing on or off as the sample's shell has it, and off with no
 *  shell. Keyed by the sample, so its shell's state starts again when the
 *  sample changes. */
function SampleSettings({ sample }: { sample: SampleId }) {
  const sampleShell = useSampleShell(sample)
  const app = useSampleApp(sample)
  const shell: Shell | null = sampleShell && { ...sampleShell, app }
  return (
    <>
      <SettingsView shell={shell} writing={sampleWriting(sample)} payloadHref={() => `#${PAYLOAD_ID}`} />
      <section aria-labelledby={PAYLOAD_ID} className="space-y-4">
        <h2 id={PAYLOAD_ID} className="font-display text-heading text-ink">
          What a draft sends
        </h2>
        <PayloadView
          payload={SAMPLE_PAYLOAD}
          on={shell?.settings.sharing?.on ?? false}
          shared={sampleSharedDraft(sample)}
        />
      </section>
    </>
  )
}

const SAMPLE_APP: AppSettings = {
  startWithSystem: true,
  keepRunningOnClose: false,
  checkForUpdates: true,
  diagnostic: false,
  update: { state: 'ready', version: '0.0.1-sample' },
  onboarded: true,
  askAutostart: false,
  canAutostart: true,
  rulesText: 31000,
  firstData: { state: 'idle' },
  version: '0.0.0-sample',
  platform: 'linux',
}

/** How long the sample's App section takes to answer. */
const SAMPLE_APP_MS = 400

/** The sample's App section: invented values kept in memory. Every action
 *  answers after a moment; in "A save fails" each is refused, and "Check now" and
 *  "Restart to update" answer that the reference page cannot do them. */
function useSampleApp(sample: SampleId): NonNullable<Shell['app']> {
  const [settings, setSettings] = useState<AppSettings>(SAMPLE_APP)
  const answer = (ok: Saved): Promise<Saved> =>
    new Promise((resolve) =>
      window.setTimeout(
        () => resolve(sample === 'fails' ? { ok: false, error: 'The folder could not be opened.' } : ok),
        SAMPLE_APP_MS,
      ),
    )
  return {
    settings,
    set: async (change) => {
      const saved = await answer({ ok: true })
      if (saved.ok)
        setSettings((current) => {
          const next = { ...current, ...change }
          return { ...next, update: next.checkForUpdates ? SAMPLE_APP.update : { state: 'idle' } }
        })
      return saved
    },
    checkForUpdates: () => answer({ ok: false, error: 'Not available on the reference page.' }),
    restartToUpdate: () => answer({ ok: false, error: 'Not available on the reference page.' }),
    showLogs: () => answer({ ok: true }),
    exportDiagnostics: () => answer({ ok: true }),
    showDataFolder: () => answer({ ok: true }),
    recheck: () => answer({ ok: true }),
    firstData: () => answer({ ok: true }),
    finishOnboarding: () => answer({ ok: true }),
  }
}

/** The indicator and the receipt in each of its states, as a draft's page
 *  draws them under its header. "Shared" undoes after a moment, and in
 *  "A save fails" the undo is refused. Keyed by the sample, so an undo
 *  starts again when the sample changes. */
function DraftPageSamples({ sample }: { sample: SampleId }) {
  const samples = [
    { label: 'The indicator', line: <SharingNote on /> },
    { label: 'Waiting', line: <DraftReceipt shared={{ state: 'waiting', at: null }} /> },
    {
      label: 'Shared',
      line: <DraftReceipt shared={{ state: 'shared', at: SAMPLE_SENT_AT }} unshare={() => sampleUnshare(sample)} />,
    },
    { label: 'Removed', line: <DraftReceipt shared={{ state: 'removed', at: SAMPLE_SENT_AT }} /> },
  ]
  return (
    <section aria-labelledby="draft-page-title" className="space-y-4">
      <h2 id="draft-page-title" className="font-display text-heading text-ink">
        On a draft's page
      </h2>
      <div className="grid gap-6 lg:grid-cols-2">
        {samples.map(({ label, line }) => (
          <div key={label} className="space-y-2">
            <SectionLabel>{label}</SectionLabel>
            {line}
          </div>
        ))}
      </div>
    </section>
  )
}

/** The Detailed Logs drawing in both its sizes: the Arena step's, and the
 *  Home banner's (`compact`). Its words are the catalogue's, in the
 *  dashboard's language. */
function DetailedLogsSamples() {
  const samples = [
    { label: 'Full size', compact: false },
    { label: 'Compact', compact: true },
  ]
  return (
    <section aria-labelledby="detailed-logs-title" className="space-y-4">
      <h2 id="detailed-logs-title" className="font-display text-heading text-ink">
        Where Detailed Logs are
      </h2>
      <p className="text-body text-muted">The drawing on the Arena step and, compact, on Home's banner.</p>
      <div className="space-y-6">
        {samples.map(({ label, compact }) => (
          <div key={label} className="space-y-2">
            <SectionLabel>{label}</SectionLabel>
            <DetailedLogsGuide compact={compact} />
          </div>
        ))}
      </div>
    </section>
  )
}

const SAMPLE_PROMPT = 'You are a coach. Read the games below and say what to change.'
const SAMPLE_PROSE =
  'You kept seven-card hands that had two lands in nine of your last forty games, and won three of them.'

/** How long the sample takes to write its report. */
const SAMPLE_WRITE_MS = 400

/** The section of two report cards, one for each writer: nobody, and a
 *  key of the viewer's. */
function WritingSamples() {
  const samples: { label: string; writer: Writer }[] = [
    { label: 'Nobody', writer: { by: 'nobody' } },
    { label: 'A key of your own', writer: { by: 'key' } },
  ]
  return (
    <section aria-labelledby="writing-title" className="space-y-4">
      <h2 id="writing-title" className="font-display text-heading text-ink">
        Writing a report
      </h2>
      <p className="text-body text-muted">One card, by who writes the report.</p>
      <div className="grid gap-6 lg:grid-cols-2">
        {samples.map(({ label, writer }) => (
          <div key={label} className="space-y-2">
            <SectionLabel>{label}</SectionLabel>
            <SampleWriting writer={writer} />
          </div>
        ))}
      </div>
    </section>
  )
}

/** One sample report card. A card whose writer writes starts empty, and a
 *  press on its button writes the invented report after a moment, with no
 *  request; one with no writer starts with the invented report, and its
 *  Save replaces that with the pasted text, in memory, with no request. */
function SampleWriting({ writer }: { writer: Writer }) {
  const writes = writer.by === 'key'
  const [narrative, setNarrative] = useState<string | null>(writes ? null : SAMPLE_PROSE)
  const [generating, setGenerating] = useState(false)

  useEffect(() => {
    if (!generating) return
    const timer = window.setTimeout(() => {
      setNarrative(SAMPLE_PROSE)
      setGenerating(false)
    }, SAMPLE_WRITE_MS)
    return () => window.clearTimeout(timer)
  }, [generating])

  return (
    <GenerateCard
      title="Coach report"
      writer={writer}
      prompt={SAMPLE_PROMPT}
      narrative={narrative}
      onGenerate={() => setGenerating(true)}
      generating={generating}
      save={async (answer) => setNarrative(answer)}
    />
  )
}
