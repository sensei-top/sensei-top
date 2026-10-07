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
