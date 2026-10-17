import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { FirstData, FirstDataProgress, Saved } from '../../bridge'
import type { TFunction } from '../../i18n'
import { failureOf, settle } from '../../lib/settings'
import { formatCount } from '../../lib/time'
import { withStop } from '../../lib/welcome'
import { PressButton } from '../settings/SaveButton'
import { Meter } from '../ui'

const megabytes = (bytes: number) => Math.round(bytes / 1_000_000)

/** What the running state says, from the shell's parsed event. */
function progressSentence(progress: FirstDataProgress | undefined, t: TFunction): string {
  if (!progress) return t('common.cardData.progressStart')
  if (progress.stage === 'save') return t('common.cardData.progressSave')
  return progress.total === null
    ? t('common.cardData.progressSoFar', { done: megabytes(progress.done) })
    : t('common.cardData.progressOf', { done: megabytes(progress.done), total: megabytes(progress.total) })
}

function CardsMeter({ progress }: { progress: FirstDataProgress | undefined }) {
  const { t } = useTranslation()
  const label = t('common.cardData.meterLabel')
  if (progress?.stage === 'download' && progress.total) {
    return <Meter fraction={progress.done / progress.total} color="accent" label={label} />
  }
  return <Meter fraction={0} color="accent" label={label} indeterminate />
}

/** The card-data download once it has started: the meter and a sentence
 *  while it runs, the count when it is done, the reason and Try again when
 *  it failed. Idle draws nothing, since what starts a download differs by
 *  page. `count` is the rules-text count the doctor reports. */
export function CardDataProgress({
  state,
  count,
  retry,
}: {
  state: FirstData
  count: number | null
  retry: () => Promise<Saved>
}) {
  const { t } = useTranslation()
  const [failure, setFailure] = useState<string | null>(null)
  // A refusal left by an earlier press is stale once a run has started.
  if (state.state === 'running' && failure !== null) setFailure(null)
  if (state.state === 'idle') return null
  if (state.state === 'running') {
    return (
      <div className="space-y-2">
        <CardsMeter progress={state.progress} />
        <p role="status" className="break-words text-body text-ink2">
          {progressSentence(state.progress, t)}
        </p>
      </div>
    )
  }
  if (state.state === 'done') {
    return (
      <p className="text-body text-ink2">
        {!count ? t('common.cardData.doneEmpty') : t('common.cardData.done', { n: formatCount(count) })}
      </p>
    )
  }
  const again = async (): Promise<boolean> => {
    setFailure(null)
    const sentence = failureOf(await settle(retry(), t), t)
    setFailure(sentence)
    return sentence === null
  }
  return (
    <div className="space-y-1.5">
      <p className="break-words text-body text-loss">
        {t('common.cardData.failed', { reason: withStop(state.error) })}
      </p>
      <PressButton
        variant="quiet"
        label={t('common.cardData.tryAgain')}
        workingLabel={t('common.cardData.starting')}
        doneLabel={null}
        onPress={again}
      />
      {failure && failure !== withStop(state.error) && failure !== state.error && <p className="break-words text-caption text-loss">{failure}</p>}
    </div>
  )
}
