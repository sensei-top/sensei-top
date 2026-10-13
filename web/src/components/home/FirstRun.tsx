import { useTranslation } from 'react-i18next'
import type { LiveStatus } from '../../api'
import type { TFunction } from '../../i18n'
import { firstRunSteps } from '../../lib/home'
import { OnboardingSteps, SectionLabel } from '../ui'

// A watcher that died after starting reads `watching: false` too, so it is
// asked first; the rest is the status panel's own sentence.
const steps = (live: LiveStatus | undefined, t: TFunction) => [
  {
    title: t('home.firstRun.watchingTitle'),
    detail: live?.watcher_stopped ? t('shell.liveStatus.watcherStopped') : t('shell.liveStatus.notWatching'),
  },
  {
    title: t('home.firstRun.logTitle'),
    detail: t('home.firstRun.logDetail'),
  },
  {
    title: t('home.firstRun.playTitle'),
    detail: t('home.firstRun.playDetail'),
  },
]

/** Home before anything is recorded: what this page is, the three steps to
 *  a first match read from the heartbeat (the first one not done says what
 *  to do), and what will appear. */
export function FirstRun({ live }: { live: LiveStatus | undefined }) {
  const { t } = useTranslation()
  const states = firstRunSteps(live)
  const willAppear = [t('home.firstRun.appear1'), t('home.firstRun.appear2'), t('home.firstRun.appear3')]
  return (
    <section className="space-y-6 rounded-hero border border-edge bg-surface px-5 py-6 shadow-lift md:px-9 md:py-8">
      <div className="space-y-2">
        <h2 className="font-display text-heading text-ink md:text-hero">{t('home.firstRun.title')}</h2>
        <p className="max-w-prose text-lead text-ink2">{t('home.firstRun.lead')}</p>
      </div>
      <div className="max-w-3xl">
        <OnboardingSteps steps={steps(live, t).map((step, index) => ({ ...step, state: states[index] }))} />
      </div>
      <div className="space-y-2">
        <SectionLabel>{t('home.firstRun.willAppear')}</SectionLabel>
        <ul className="max-w-prose list-disc space-y-1 pl-5 text-body text-ink2 marker:text-muted">
          {willAppear.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </div>
    </section>
  )
}
