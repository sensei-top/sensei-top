import { useState } from 'react'
import { createPortal } from 'react-dom'

const PREVIEW_WIDTH = 240
const CARD_ASPECT = 680 / 488

/** The whole card at preview size, portalled to `document.body` so a
 *  scrolling turn list or table can never clip it, positioned from its
 *  anchor's own bounding rect and flipped above/below to stay on screen.
 *  Exported for `CardArt`, whose button shows the whole card through it.
 *  The picture is shown whole: never cropped, covered, stretched, tinted
 *  or blurred.
 *  When the image does not load, the card's name stands in its place as
 *  text, as it does for `CardImage`: never a broken image.
 *  The name sits against its anchor, under it or over it, wherever the
 *  picture would have opened. */
export function CardPreview({ grpId, name, anchor }: { grpId: number; name: string; anchor: DOMRect }) {
  // Keyed by id, so a preview reused for another card tries its image anew.
  const [failed, setFailed] = useState<number | null>(null)
  const height = PREVIEW_WIDTH * CARD_ASPECT
  const margin = 8
  const showBelow =
    anchor.bottom + margin + height <= window.innerHeight || anchor.top - margin - height < 0
  const top = showBelow ? anchor.bottom + margin : anchor.top - margin - height
  const left = Math.min(
    Math.max(anchor.left + anchor.width / 2 - PREVIEW_WIDTH / 2, margin),
    window.innerWidth - PREVIEW_WIDTH - margin,
  )
  return createPortal(
    failed === grpId ? (
      <span
        className="pointer-events-none fixed rounded-control border border-edge bg-surface3 px-3 py-2 text-caption text-ink shadow-lift"
        style={
          showBelow
            ? { top, left, maxWidth: PREVIEW_WIDTH }
            : { bottom: window.innerHeight - anchor.top + margin, left, maxWidth: PREVIEW_WIDTH }
        }
      >
        {name}
      </span>
    ) : (
      <img
        src={`/api/cards/${grpId}/image`}
        alt={name}
        className="pointer-events-none fixed rounded-lg shadow-xl"
        style={{ top, left, width: PREVIEW_WIDTH }}
        onError={() => setFailed(grpId)}
      />
    ),
    document.body,
  )
}

/**
 * A card's picture from the local API, which caches Scryfall's 'normal'
 * image on first sight. Two failure modes are deliberately distinct: a card
 * hidden from us (no grpId at all — an opponent's hand, say) renders a
 * card-shaped placeholder, since there really is a card there, we just
 * cannot see it. An id Scryfall cannot map, or being offline, still falls
 * back to the name as text via onError, since those are genuinely "we don't
 * know what this is."
 *
 * Hovering a loaded thumbnail shows the same cached image at preview size —
 * no second Scryfall fetch, just a bigger render of the browser-cached file.
 */
export function CardImage({
  grpId,
  name,
  className = 'w-10 aspect-[488/680] rounded object-cover',
}: {
  grpId: number | null | undefined
  name: string
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  const [anchor, setAnchor] = useState<DOMRect | null>(null)

  if (grpId == null) {
    return (
      <span
        className={`${className} inline-block border border-dashed border-edge bg-surface`}
        title={name}
      />
    )
  }
  if (failed) {
    return (
      <span className="inline-block rounded border border-edge bg-surface px-1.5 py-0.5 text-caption text-ink2">
        {name}
      </span>
    )
  }
  return (
    <>
      <img
        src={`/api/cards/${grpId}/image`}
        alt={name}
        title={name}
        loading="lazy"
        onError={() => setFailed(true)}
        onMouseEnter={(e) => setAnchor(e.currentTarget.getBoundingClientRect())}
        onMouseLeave={() => setAnchor(null)}
        className={className}
      />
      {anchor && <CardPreview grpId={grpId} name={name} anchor={anchor} />}
    </>
  )
}
