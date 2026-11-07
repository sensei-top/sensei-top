import { useTranslation } from 'react-i18next'
import type { FirstData } from '../bridge'
import { TextLink } from '../components/ui'
import { cardDataWords, useCardData } from './cardData'

/** A quiet chip beside the tracker's state while the card data downloads:
 *  a link to Settings → Sources. Nothing when idle, done or in a browser. */
export function CardDataChipView({ state, className = '' }: { state: FirstData | null; className?: string }) {
  const { t } = useTranslation()
  const words = cardDataWords(state, t)
  if (words === null) return null
  return (
    <TextLink href="/settings/sources" muted className={`shrink-0 text-caption ${className}`}>
      {words}
    </TextLink>
  )
}

export function CardDataChip({ className = '' }: { className?: string }) {
  return <CardDataChipView state={useCardData()} className={className} />
}
