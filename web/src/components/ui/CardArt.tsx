import { Maximize2 } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { CardPreview } from '../CardImage'
import { Button } from './Button'
import { useTranslation } from 'react-i18next'

export type ArtFade = 'none' | 'down' | 'left' | 'right'

// The colour a fade arrives at is the surface behind the box, which that
// surface names in `--art-surface` (Card and the nested blocks set it). A
// box on no such surface sits on the page itself: the plane. The last 15%
// of the fade is that colour alone, the band where text may begin.
const FADE_TO = 'var(--art-surface, var(--plane))'
// The wash of a box with no card: docs/design-system.md, "Card art".
const WASH_DIRECTION = { none: '135deg', down: 'to bottom', left: 'to left', right: 'to right' }
const FADE: Record<Exclude<ArtFade, 'none'>, string> = {
  down: `linear-gradient(to bottom, transparent 35%, ${FADE_TO} 85%)`,
  left: `linear-gradient(to left, transparent 35%, ${FADE_TO} 85%)`,
  right: `linear-gradient(to right, transparent 35%, ${FADE_TO} 85%)`,
}

/** Whether the art at `src` loaded. The picture is a CSS background, which
 *  reports nothing, so an `Image` asks for the same URL first; the
 *  background is set only once it has arrived, and it then comes from the
 *  browser's cache. */
function useLoaded(src: string | null): boolean {
  const [loaded, setLoaded] = useState<string | null>(null)
  useEffect(() => {
    if (src == null) return
    const probe = new Image()
    probe.onload = () => setLoaded(src)
    probe.src = src
    return () => {
      probe.onload = null
    }
  }, [src])
  return src != null && loaded === src
}

/** The corner button. The whole card opens on hover (a mouse), on keyboard
 *  focus, and on tap (a touch or a pen, where there is no hover). It closes
 *  when the pointer leaves, focus leaves, Escape is pressed, the page
 *  scrolls (the preview is placed once, from the button's rect), or a tap
 *  lands anywhere else, a second tap on the button included. */
function ShowCardButton({ grpId, name }: { grpId: number; name: string | null }) {
  const { t } = useTranslation()
  const button = useRef<HTMLButtonElement>(null)
  const pointer = useRef<string>('')
  const [anchor, setAnchor] = useState<DOMRect | null>(null)
  const open = () => setAnchor(button.current?.getBoundingClientRect() ?? null)
  const close = () => setAnchor(null)

  useEffect(() => {
    if (anchor == null) return
    const onPointerDown = (event: globalThis.PointerEvent) => {
      if (!button.current?.contains(event.target as Node)) setAnchor(null)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setAnchor(null)
    }
    const onScroll = () => setAnchor(null)
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [anchor])

  const fromMouse = (event: PointerEvent) => event.pointerType === 'mouse'

  return (
    <>
      <Button
        ref={button}
        variant="secondary"
        size="sm"
        iconOnly
        aria-label={name ? t('common.showCardNamed', { name }) : t('common.showCard')}
        aria-expanded={anchor != null}
        className="absolute top-2 right-2"
        onPointerDown={(event) => {
          pointer.current = event.pointerType
        }}
        onPointerEnter={(event) => fromMouse(event) && open()}
        onPointerLeave={(event) => fromMouse(event) && close()}
        onFocus={(event) => event.currentTarget.matches(':focus-visible') && open()}
        onBlur={close}
        onClick={() => {
          // A mouse has already opened it on hover; a tap, or Enter/Space
          // on the keyboard, toggles it.
          const byMouse = pointer.current === 'mouse'
          pointer.current = ''
          if (byMouse) return
          if (anchor == null) open()
          else close()
        }}
      >
        <Maximize2 size={16} strokeWidth={2} aria-hidden />
      </Button>
      {anchor && <CardPreview grpId={grpId} name={name ?? t('common.theCard')} anchor={anchor} />}
    </>
  )
}

/**
 * A card's art alone, from the local API's art route
 * (`/api/cards/{id}/art`), which caches Scryfall's `art_crop` on first
 * sight. It is its own picture, never a crop of the whole card image:
 * that would cut off the artist's name and the copyright line
 * (docs/attribution.md).
 *
 * The picture keeps its own colours: no opacity, filter or blend mode on
 * it. `fade` is a gradient at one edge, from transparent to the colour of
 * the surface behind the box; text sits where the gradient has arrived,
 * never on the picture.
 *
 * Art is never the only carrier of anything. A picture that does not load
 * (a new install, offline, a card Scryfall cannot map) leaves the surface
 * behind the box showing. With no id the box draws a quiet wash,
 * `aria-hidden`, running toward the fade's edge. Neither has a button.
 *
 * The button in the corner shows the whole card on hover, on focus and
 * on tap. It is how a viewer finds the artist's name and the copyright
 * line, which Scryfall's rules ask of art shown alone.
 */
export function CardArt({
  grpId,
  name,
  y = 30,
  fade = 'none',
  className = '',
}: {
  grpId: number | null
  name: string | null
  /** Where the picture sits vertically inside the box, in percent: 0 shows
   *  its top, 100 its bottom. */
  y?: number
  fade?: ArtFade
  /** The box's shape: its size, its radius, its place. */
  className?: string
}) {
  const src = grpId == null ? null : `/api/cards/${grpId}/art`
  const loaded = useLoaded(src)
  const style = {
    '--art-y': `${y}%`,
    backgroundImage: loaded ? `url(${src})` : grpId == null ? `linear-gradient(${WASH_DIRECTION[fade]}, var(--surface-2), ${FADE_TO})` : undefined,
  } as CSSProperties

  return (
    // The box itself takes no position of its own, so the caller's
    // `className` places it (`absolute` included); the inner layer is the
    // fade's and the button's positioned ancestor, filling the box.
    <div aria-hidden={grpId == null ? true : undefined} className={`card-art ${className}`} style={style}>
      {loaded && grpId != null && (
        <div className="relative h-full w-full">
          {fade !== 'none' && (
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0"
              style={{ backgroundImage: FADE[fade] }}
            />
          )}
          <ShowCardButton grpId={grpId} name={name} />
        </div>
      )}
    </div>
  )
}
