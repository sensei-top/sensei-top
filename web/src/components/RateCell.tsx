import { useTranslation } from 'react-i18next'
import { rateCell } from '../lib/sample'

/** A table's Rate cell, by the small-sample rule (`rateCell`): an em dash
 *  with nothing won or lost, otherwise its text, muted under ten — a rough
 *  rate from five, "too few" under five — on one line
 *  (`whitespace-nowrap`). `games` counts games rather than matches. */
export function RateCell({ wins, losses, games = false }: { wins: number; losses: number; games?: boolean }) {
  const { t } = useTranslation()
  const cell = rateCell({ wins, losses }, t, games ? 'games' : 'matches')
  if (cell == null) return <>—</>
  return cell.muted ? <span className="whitespace-nowrap text-muted">{cell.text}</span> : <>{cell.text}</>
}
