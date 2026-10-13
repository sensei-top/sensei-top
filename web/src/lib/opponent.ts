import type { TFunction } from '../i18n'

/** Strips the colour-fallback prefix `v_match_opponent` puts on a label when
 *  no archetype matched (`migrations/030_opponent_colors.sql`:
 *  `COALESCE(NULLIF(v.colors, ''), ...) || ' ' || char(183) || ' ' ||
 *  v.signature_card`, e.g. "UR · Mox Opal"). A `ManaPips` rendering of the
 *  same colours already sits beside the label everywhere this is used, so
 *  the colours would otherwise read twice — the pips, then the text.
 *
 *  Display-only: `opponent_key` and the stored label are untouched by this,
 *  and nothing may match against the stripped text it returns — only render
 *  it. */
export function opponentLabelText(label: string, colors: string | null | undefined): string {
  if (!colors) return label
  const prefix = `${colors} · `
  return label.startsWith(prefix) ? label.slice(prefix.length) : label
}

/** The classifier's confidence word as the viewer reads it. A word this
 *  table does not know (a newer server) is shown as it arrived. */
export function confidenceLabel(confidence: string, t: TFunction): string {
  switch (confidence) {
    case 'high':
      return t('live.confidence.high')
    case 'medium':
      return t('live.confidence.medium')
    case 'low':
      return t('live.confidence.low')
    case 'unknown':
      return t('live.confidence.unknown')
    default:
      return confidence
  }
}
