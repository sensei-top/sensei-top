import { useShell, type FirstData, type FirstDataProgress } from '../bridge'
import type { TFunction } from '../i18n'

/** Where the card-data download stands, from the shell's bridge. `null` in
 *  a browser, which has no bridge and no download to report. */
export function useCardData(): FirstData | null {
  return useShell()?.app?.settings.firstData ?? null
}

/** The download's whole percent, or `null` when it has no total (or is saving). */
export function cardDataPercent(progress: FirstDataProgress | undefined): number | null {
  if (progress?.stage !== 'download' || !progress.total) return null
  return Math.min(100, Math.round((progress.done / progress.total) * 100))
}

/** The chip's words for a state, or `null` when the state shows nothing. */
export function cardDataWords(state: FirstData | null, t: TFunction): string | null {
  if (!state) return null
  if (state.state === 'failed') return t('shell.cardData.failed')
  if (state.state !== 'running') return null
  if (state.progress?.stage === 'save') return t('shell.cardData.saving')
  const pct = cardDataPercent(state.progress)
  return pct === null ? t('shell.cardData.downloading') : t('shell.cardData.percent', { pct })
}
