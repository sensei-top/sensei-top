import { useTranslation } from 'react-i18next'
import type { LiveStatus } from '../../api'
import type { TFunction } from '../../i18n'
import { firstRunSteps } from '../../lib/home'
import { DetailedLogsBody, type DetailedLogsInputs } from './DetailedLogsBanner'
import { OnboardingSteps, SectionLabel } from '../ui'

// A watcher that died after starting reads `watching: false` too, so it is
// asked first; the rest is the status panel's own sentence.
const watcherDetail = (live: LiveStatus | undefined, t: TFunction) =>
  live?.watcher_stopped ? t('shell.liveStatus.watcherStopped') : t('shell.liveStatus.notWatching')

const steps = (live: LiveStatus | undefined, t: TFunction, shell: FirstRunShell | undefined) => {
  if (shell?.mtgoOnly) {
    return [
      {
        title: t('home.firstRun.mtgoWatchingTitle'),
        detail: live?.watcher_stopped ? t('home.firstRun.mtgoWatcherStopped') : t('home.firstRun.mtgoNotWatching'),
      },
      {
        title: t('home.firstRun.mtgoFolderTitle'),
        // Only when no folder is set, so it never says so of one that is set
        // and not yet watched.
        detail: shell.mtgoDir === null ? t('home.firstRun.mtgoFolderDetail') : undefined,
      },
      { title: t('home.firstRun.mtgoPlayTitle'), detail: t('home.firstRun.mtgoPlayDetail') },
    ]
  }
  return [
    { title: t('home.firstRun.watchingTitle'), detail: watcherDetail(live, t) },
    {
      title: t('home.firstRun.logTitle'),
      // With a shell and the nag, the drawing and Check again; without, the
      // sentence.
      detail: shell?.banner ? <DetailedLogsBody {...shell.banner} /> : t('home.firstRun.logDetail'),
    },
    { title: t('home.firstRun.playTitle'), detail: t('home.firstRun.playDetail') },
  ]
}

/** What the shell adds to first run; absent in a browser. */
export type FirstRunShell = {
  /** The Detailed Logs inputs while the nag holds, else `null`. */
  banner: DetailedLogsInputs | null
  /** The user plays Magic Online alone. */
  mtgoOnly: boolean
  /** The saved folder of MTGO game logs, `null` when unset. */
  mtgoDir: string | null
}

/** Home before anything is recorded: what this page is, the three steps to
 *  a first match read from the heartbeat (the first one not done says what
 *  to do), and what will appear. */
export function FirstRun({ live, shell }: { live: LiveStatus | undefined; shell?: FirstRunShell }) {
  const { t } = useTranslation()
  const states = firstRunSteps(live, shell?.mtgoOnly)
  const willAppear = [t('home.firstRun.appear1'), t('home.firstRun.appear2'), t('home.firstRun.appear3')]
  return (
    <section className="space-y-6 rounded-hero border border-edge bg-surface px-5 py-6 shadow-lift md:px-9 md:py-8">
      <div className="space-y-2">
        <h2 className="font-display text-heading text-ink md:text-hero">{t('home.firstRun.title')}</h2>
        <p className="max-w-prose text-lead text-ink2">{shell?.mtgoOnly ? t('home.firstRun.mtgoLead') : t('home.firstRun.lead')}</p>
      </div>
      <div className="max-w-3xl">
        <OnboardingSteps steps={steps(live, t, shell).map((step, index) => ({ ...step, state: states[index] }))} />
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
