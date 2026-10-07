import type { LiveStatus } from '../../api'
import { firstRunSteps, NOT_WATCHING_SENTENCE, watcherCallout } from '../../lib/home'
import { OnboardingSteps, SectionLabel } from '../ui'

const steps = (live: LiveStatus | undefined) => [
  {
    title: 'The tracker is watching Arena',
    detail: watcherCallout(live) ?? NOT_WATCHING_SENTENCE,
  },
  {
    title: 'Arena is writing its log',
    detail:
      'Nothing has arrived from Arena yet. Start Arena. If it is already open, turn on Detailed Logs (Plugin Support) in Arena, under Options, then Account, and start Arena again.',
  },
  {
    title: 'Play a match',
    detail: 'The tracker can see Arena. Play a match, and it appears here when it ends.',
  },
]

const WILL_APPEAR = [
  'Your last session in one line, and your record over the last 30 days.',
  'Three things worth a look: your last match, a pattern across your matches, and the field.',
  'Your recent matches, your win rate by week and your decks.',
]

/** Home before anything is recorded: what this page is, the three steps to
 *  a first match read from the heartbeat (the first one not done says what
 *  to do), and what will appear. */
export function FirstRun({ live }: { live: LiveStatus | undefined }) {
  const states = firstRunSteps(live)
  return (
    <section className="space-y-6 rounded-hero border border-edge bg-surface px-5 py-6 shadow-lift md:px-9 md:py-8">
      <div className="space-y-2">
        <h2 className="font-display text-heading text-ink md:text-hero">This page fills in as you play</h2>
        <p className="max-w-prose text-lead text-ink2">
          Sensei Top reads the log Arena writes while you play. Nothing is recorded yet.
        </p>
      </div>
      <div className="max-w-3xl">
        <OnboardingSteps steps={steps(live).map((step, index) => ({ ...step, state: states[index] }))} />
      </div>
      <div className="space-y-2">
        <SectionLabel>What will appear here</SectionLabel>
        <ul className="max-w-prose list-disc space-y-1 pl-5 text-body text-ink2 marker:text-muted">
          {WILL_APPEAR.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
    </section>
  )
}
