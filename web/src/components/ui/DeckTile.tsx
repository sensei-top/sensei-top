import { Link } from 'react-router'
import { CardArt } from './CardArt'
import { useTranslation } from 'react-i18next'

/** One of the viewer's decks as a tile: a card's art on top, then the
 *  deck's name, its record, a second line when the caller has one, and
 *  when it was last played. The words under the art are the tile's way in
 *  (a row's way in, docs/design-system.md's "Links"); the art keeps its own
 *  button, so it sits outside the link.
 *
 *  The record comes in two parts the caller writes: `figure`, the large
 *  number ("58%", "6–3"; under ten matches drawn muted, the rate from
 *  five, the record under five),
 *  absent when there is none, and `line`, the words under it. No mana pips:
 *  nothing names a deck's own colours. A deck with no name reads "Unnamed
 *  deck", in muted text. */
export function DeckTile({
  name,
  href,
  figure,
  muted = false,
  line,
  detail,
  lastPlayed,
  art,
}: {
  name: string | null
  /** A place in the app: the deck's own page. */
  href: string
  figure?: string | null
  /** The figure is a record under the small-sample threshold: drawn muted. */
  muted?: boolean
  line: string
  /** A line above the last played, "Standard, best of three · 4 versions"
   *  (`/decks`); absent on Home. */
  detail?: string | null
  /** The whole phrase, "last played Sep 27". */
  lastPlayed?: string | null
  /** A card the viewer cast with this deck; the box stands empty without. */
  art?: { grpId: number; name: string | null } | null
}) {
  const { t } = useTranslation()
  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden rounded-card border border-edge bg-surface shadow-lift [--art-surface:var(--surface-1)]">
      <CardArt grpId={art?.grpId ?? null} name={art?.name ?? null} fade="down" className="h-[72px] md:h-[92px]" />
      <div className="flex flex-1 flex-col p-1.5">
        <Link
          to={href}
          className="flex min-h-[44px] flex-1 flex-col rounded-control px-2.5 py-2 transition-chrome hover:bg-surface3"
        >
          <span className={`font-display text-title break-words ${name ? 'text-ink' : 'text-muted'}`}>
            {name ?? t('common.unnamedDeck')}
          </span>
          {figure && <span className={`mt-2 font-display text-stat ${muted ? 'text-muted' : 'text-ink'}`}>{figure}</span>}
          <span className={`text-caption text-ink2 ${figure ? '' : 'mt-2'}`}>{line}</span>
          {(detail || lastPlayed) && (
            <span className="mt-auto flex flex-col pt-1 text-caption text-muted">
              {detail && <span>{detail}</span>}
              {lastPlayed && <span>{lastPlayed}</span>}
            </span>
          )}
        </Link>
      </div>
    </div>
  )
}
