import type { KeepGuideOut, LibraryCardOut } from '../api'
import { probAtLeastOneIn } from '../lib/odds'
import { Card, EmptyState, Meter, SectionLabel } from './ui'

const pct = (p: number): string => `${Math.round(p * 100)}%`

type Tile = {
  key: string
  label: string
  primary: string
  primaryCap: string
  secondary?: string
  secondaryCap?: string
  meterFraction: number
  meterColor: 's1' | 's3'
  foot?: string
}

/** One odds readout: a big "next draw" figure, a smaller "within three"
 *  figure below it, and a meter — the aggregate numbers that actually vary
 *  from game to game, unlike a single card's per-row odds (see this file's
 *  own module comment for why those were demoted). Each number shares its
 *  line with its words and never shrinks: the words wrap beside it. */
function OddsTile({ tile }: { tile: Tile }) {
  return (
    <div className="rounded-block border border-edge bg-plane px-4 py-3.5">
      <SectionLabel as="div">{tile.label}</SectionLabel>
      <div className="mt-1.5 flex items-baseline gap-2 tabular-nums">
        <span className="shrink-0 font-display text-display text-ink">{tile.primary}</span>
        <span className="min-w-0 text-body text-ink2">{tile.primaryCap}</span>
      </div>
      {tile.secondary != null && (
        <div className="mt-1 flex items-baseline gap-2 tabular-nums">
          <span className="shrink-0 font-display text-heading text-ink">{tile.secondary}</span>
          <span className="min-w-0 text-body text-ink2">{tile.secondaryCap}</span>
        </div>
      )}
      <Meter fraction={tile.meterFraction} color={tile.meterColor} height="h-2" className="mt-2.5" />
      {tile.foot && <p className="mt-2 text-caption tabular-nums text-muted">{tile.foot}</p>}
    </div>
  )
}

/** The tab's primary panel once a game is under way: this deck's own
 *  remaining library — the one thing every competing MTG Arena tracker
 *  leads with, and the one thing Arena genuinely does not show. Sourced
 *  from a fresh live replay (`table/live.py`), not the projected `turns`
 *  row `NextDrawsCard.tsx` used to read (client-side, capped at 8 rows) —
 *  that row can run 8-15s+ stale mid-combat on a real database
 *  (`projector/live_state.py`'s module docstring has the numbers).
 *
 *  A header band of large odds readouts sits above a decklist grouped by
 *  mana value, replacing a single four-column table whose per-row odds
 *  were `text-caption text-muted` — the smallest, dimmest type in the panel,
 *  set that way for a number that is mostly redundant: P(next draw) is
 *  exactly `left ÷ libraryCount`, so every 4-of read the same percentage
 *  regardless of which 4-of it was. The band spends large type on the
 *  aggregate figures that actually vary from game to game; the list keeps
 *  one percentage per row (within three draws, the horizon whose values
 *  spread widest) and sorts by name rather than copies left, so a row
 *  never jumps position as the game evolves. Lands collapse into the
 *  header band's own tile rather than a summary row in the list — that is
 *  where they were always the headline. No card cap: the fresh replay
 *  costs the same either way.
 */
export function LibraryCard({
  cards,
  libraryCount,
  keep,
}: {
  cards: LibraryCardOut[] | undefined
  libraryCount: number | null | undefined
  keep: KeepGuideOut | null | undefined
}) {
  if (!cards) return null
  if (libraryCount == null || (cards.length === 0 && libraryCount > 0)) {
    return (
      <Card
        title="Your library"
        subtitle={libraryCount != null ? `${libraryCount} cards left` : undefined}
        className="flex h-full min-h-0 flex-col"
      >
        <EmptyState message="Nothing left to draw, or the library count isn't known yet." />
      </Card>
    )
  }

  const nonLands = cards.filter((c) => !c.is_land)
  const lands = cards.filter((c) => c.is_land)
  const landsLeft = lands.reduce((sum, c) => sum + c.left, 0)

  const landTile: Tile = {
    key: 'land',
    label: 'Land · next draw',
    primary: pct(probAtLeastOneIn(libraryCount, landsLeft, 1)),
    primaryCap: 'on the top card',
    secondary: pct(probAtLeastOneIn(libraryCount, landsLeft, 3)),
    secondaryCap: 'within three draws',
    meterFraction: probAtLeastOneIn(libraryCount, landsLeft, 1),
    meterColor: 's3',
    foot: `${landsLeft} land${landsLeft === 1 ? '' : 's'} among ${libraryCount} cards`,
  }

  // Hidden outright rather than showing a fabricated "0% interaction" when
  // `cards --scryfall` has never run (rule 4) — every nonland row's
  // is_interaction would be null in that case, never false.
  const hasInteractionData = nonLands.some((c) => c.is_interaction != null)
  const interactionLeft = nonLands
    .filter((c) => c.is_interaction === true)
    .reduce((sum, c) => sum + c.left, 0)
  const unknownInteractionLeft = nonLands
    .filter((c) => c.is_interaction == null)
    .reduce((sum, c) => sum + c.left, 0)
  const interactionTile: Tile | null = hasInteractionData
    ? {
        key: 'interaction',
        label: 'Interaction · next draw',
        primary: pct(probAtLeastOneIn(libraryCount, interactionLeft, 1)),
        primaryCap: 'on the top card',
        secondary: pct(probAtLeastOneIn(libraryCount, interactionLeft, 3)),
        secondaryCap: 'within three draws',
        meterFraction: probAtLeastOneIn(libraryCount, interactionLeft, 1),
        meterColor: 's1',
        foot:
          `${interactionLeft} removal, counter${interactionLeft === 1 ? '' : 's'} and bounce left` +
          (unknownInteractionLeft > 0 ? ` · ${unknownInteractionLeft} with no rules text yet` : ''),
      }
    : null

  const leftRatio = libraryCount > 0 ? landsLeft / libraryCount : 0
  // `keep` rides the same /api/current-match/read response KeepGuideCard
  // already reads (table/keep.py) — no second request for this comparison.
  const deckRatio = keep && keep.maindeck_size > 0 ? keep.land_count / keep.maindeck_size : null
  let floodFoot: string | undefined
  if (deckRatio != null) {
    const swing = Math.round((leftRatio - deckRatio) * 100)
    floodFoot =
      Math.abs(swing) < 2
        ? 'Running true to the deck.'
        : swing < 0
          ? `${Math.abs(swing)} points land-light — you have drawn your share.`
          : `${swing} points land-heavy — the lands are still in there.`
  }
  const floodTile: Tile = {
    key: 'flood',
    label: 'Flood and screw',
    primary: pct(leftRatio),
    primaryCap: 'of what is left is land',
    secondary: deckRatio != null ? pct(deckRatio) : undefined,
    secondaryCap: 'of the deck you built',
    meterFraction: leftRatio,
    meterColor: 's3',
    foot: floodFoot,
  }

  const tiles = [landTile, interactionTile, floodTile].filter((t): t is Tile => t != null)

  // Grouped by mana value like a decklist, the shape a player already holds
  // their own 60 in memory in. Nonlands with no parseable cost get a final
  // "Cost unknown" group rather than a fabricated mana value.
  const groups = new Map<number, LibraryCardOut[]>()
  for (const c of nonLands) {
    const key = c.mana_value ?? 99
    const group = groups.get(key)
    if (group) group.push(c)
    else groups.set(key, [c])
  }
  const sortedGroups = [...groups.entries()].sort(([a], [b]) => a - b)

  return (
    <Card
      title="Your library"
      subtitle={`${libraryCount} cards left`}
      className="flex h-full min-h-0 flex-col"
    >
      {/* Under 48rem the tiles stack, one to a row. */}
      <div
        className={`grid shrink-0 grid-cols-1 gap-3 ${tiles.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}
      >
        {tiles.map((tile) => (
          <OddsTile key={tile.key} tile={tile} />
        ))}
      </div>

      <div className="mt-4 shrink-0 border-t border-edge" />

      <div className="min-h-0 flex-1 overflow-y-auto pt-4">
        <div className="[columns:21rem_3] gap-x-10">
          {sortedGroups.map(([mv, group]) => {
            const groupLeft = group.reduce((sum, c) => sum + c.left, 0)
            // Sorted by name, not copies left: a row's position stays fixed
            // as the game evolves, rather than reshuffling on every draw.
            const sorted = [...group].sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
            return (
              <div key={mv} className="mb-4 break-inside-avoid">
                <div className="mb-1 flex items-center gap-2.5">
                  <SectionLabel as="span" className="whitespace-nowrap">
                    {mv === 99 ? 'Cost unknown' : `${mv} mana`}
                  </SectionLabel>
                  <span className="h-px flex-1 bg-edge" />
                  <span className="text-caption tabular-nums text-muted">{groupLeft}</span>
                </div>
                {sorted.map((c) => (
                  <div
                    key={c.grp_id}
                    className="grid grid-cols-[2.7rem_1fr_auto] items-baseline gap-3 py-0.5"
                  >
                    <span className="text-right text-body tabular-nums text-ink2">
                      <span className="font-semibold text-ink">{c.left}</span>/{c.quantity}
                    </span>
                    <span
                      className="min-w-0 truncate font-display text-title text-ink"
                      title={c.name ?? 'Unknown card'}
                    >
                      {c.name ?? 'Unknown card'}
                    </span>
                    <span className="text-body tabular-nums text-ink2">
                      {pct(probAtLeastOneIn(libraryCount, c.left, 3))}
                    </span>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      </div>

      <p className="mt-2 shrink-0 text-caption text-muted">
        Percentages are the odds of drawing at least one copy within three draws.
      </p>
    </Card>
  )
}
