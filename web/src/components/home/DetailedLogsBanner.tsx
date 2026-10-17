import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { DetailedLogs, Saved } from '../../bridge'
import { failureOf, settle } from '../../lib/settings'
import { PressButton } from '../settings/SaveButton'
import { DetailedLogsGuide } from '../onboarding/DetailedLogsGuide'
import { Callout } from '../ui'

export type DetailedLogsInputs = { detailedLogs: DetailedLogs; recheck: () => Promise<Saved> }

/** Home's ask to turn on Detailed Logs, shown while doctor does not read
 *  them on. Check again re-reads the setting through the shell, whose
 *  published result takes the banner away once it reads `enabled`; a check
 *  that still reads `unknown` says why nothing changed. */
export function DetailedLogsBanner(inputs: DetailedLogsInputs) {
  const { t } = useTranslation()
  return (
    <Callout tone="warn" title={t('home.detailedLogs.title')}>
      <div className="space-y-4">
          <DetailedLogsBody {...inputs} />
      </div>
    </Callout>
  )
}

/** The banner's content without its frame, which first run's log step
 *  carries as its detail: the drawing, Check again and its feedback. The
 *  banner's sentence stays with the banner, since it has no referent under
 *  first run's own title. */
export function DetailedLogsBody({ detailedLogs, recheck }: DetailedLogsInputs) {
  const { t } = useTranslation()
  const [checked, setChecked] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const press = async (): Promise<boolean> => {
    setFailure(null)
    const sentence = failureOf(await settle(recheck(), t), t)
    setFailure(sentence)
    setChecked(sentence === null)
    return sentence === null
  }
  return (
    <div className="space-y-4">
      <p>{t('home.detailedLogs.body')}</p>
      <DetailedLogsGuide compact />
      <div className="space-y-1.5">
        <PressButton
          variant="quiet"
          label={t('home.detailedLogs.checkAgain')}
          workingLabel={t('home.detailedLogs.checking')}
          doneLabel={null}
          onPress={press}
        />
        {failure && <p className="break-words text-caption text-loss">{failure}</p>}
        {checked && !failure && detailedLogs === 'unknown' && (
          <p className="text-caption text-ink2">{t('home.detailedLogs.stillOff')}</p>
        )}
      </div>
    </div>
  )
}
