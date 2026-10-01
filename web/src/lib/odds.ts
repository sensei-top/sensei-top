/** P(at least one success in `draws` cards drawn without replacement from a
 *  `libraryCount`-card library holding `successCount` copies) — the
 *  hypergeometric complement, derived sequentially so it needs no factorials.
 *  Shared between the library panel and (historically) `NextDrawsCard.tsx`,
 *  and mirrors the same read `table/hand_read.py` runs server-side for the
 *  opponent's hand, extended there to a fractional "successes" count. */
export function probAtLeastOneIn(
  libraryCount: number,
  successCount: number,
  draws: number,
): number {
  if (libraryCount <= 0 || successCount <= 0) return 0
  const n = Math.min(Math.max(draws, 0), libraryCount)
  let probNone = 1
  for (let i = 0; i < n; i++) {
    const remaining = libraryCount - i
    const nonSuccess = remaining - successCount
    if (nonSuccess <= 0) return 1
    probNone *= nonSuccess / remaining
  }
  return 1 - probNone
}
