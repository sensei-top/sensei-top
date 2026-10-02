import type { ReactNode } from 'react'
import { CardImage } from '../CardImage'

/** A whole card and what is known about it, written under the picture:
 *  nothing is drawn on the card, and nothing dims it. The picture is
 *  `CardImage`, shown whole; with no `grpId` (a card known by name with no
 *  picture on file) it is the name in a card-shaped box, which is not
 *  `CardImage`'s dashed placeholder for a card hidden from us.
 *
 *  The caption is a block under the picture, of the tile's width. Its
 *  minimum height is one line of a small `Chip`, so a row of tiles keeps
 *  one line whether or not each tile has a caption, and a caption that
 *  carries a chip is no taller than one that does not. The tile carries no
 *  `title`: what a tooltip would say belongs in the caption, or in a line
 *  under the row. */
export function CardTile({
  grpId,
  name,
  width,
  children,
}: {
  grpId: number | null | undefined
  name: string
  /** In pixels; the picture keeps the card's own 488 × 680 shape. */
  width: number
  children?: ReactNode
}) {
  return (
    <figure className="shrink-0" style={{ width }}>
      {grpId != null ? (
        <CardImage
          grpId={grpId}
          name={name}
          className="block aspect-[488/680] w-full rounded-control object-contain"
        />
      ) : (
        <span className="flex aspect-[488/680] w-full items-center justify-center rounded-control border border-edge bg-surface px-1.5 text-center text-chip text-ink2">
          {name}
        </span>
      )}
      <figcaption className="mt-1.5 min-h-5.5 text-caption tabular-nums text-ink">{children}</figcaption>
    </figure>
  )
}
