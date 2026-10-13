import { ArrowLeft } from 'lucide-react'
import type { AnchorHTMLAttributes, ReactNode, Ref } from 'react'
import { Link } from 'react-router'

type TextLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href' | 'target' | 'rel'> & {
  href: string
  ref?: Ref<HTMLAnchorElement>
  /** A reference mark in running text (a citation such as `[R4]`), which
   *  points at a source beside what the text says: muted, turning ink
   *  under the pointer. Never a link that is the text's point. */
  muted?: boolean
}

const TEXT_LINK_CLASS = 'text-ink underline decoration-muted underline-offset-2 hover:decoration-ink'
// Built whole rather than the plain class with `text-muted` added: two
// colour utilities on one element resolve by the stylesheet's order, not
// the attribute's.
const MUTED_LINK_CLASS =
  'text-muted underline decoration-line underline-offset-2 hover:text-ink hover:decoration-ink'

/** A link in or beside text. The underline is what says "link", so the
 *  colour stays the text's own: never a series colour, which is data,
 *  and never the accent, which is the brand and the primary action
 *  (docs/design-system.md). An `href` that begins with `/` is a place
 *  in the app and renders the router's `Link`, so following it never
 *  reloads the page. Anything else leaves the app and opens in a new
 *  tab. A link that acts as a control (a rail item, a table's row) is
 *  not this. `muted` is for a reference mark in running text, a
 *  citation, and never for a link that is the text's point. */
export function TextLink({ href, muted = false, className = '', ...rest }: TextLinkProps) {
  const look = `${muted ? MUTED_LINK_CLASS : TEXT_LINK_CLASS} ${className}`
  // `//host` is protocol-relative, another site, not a place in the app.
  if (href.startsWith('/') && !href.startsWith('//')) {
    return <Link to={href} {...rest} className={look} />
  }
  return <a href={href} target="_blank" rel="noreferrer" {...rest} className={look} />
}

/** The way back to a list, over the page that came from it ("All
 *  matches", "All decks"): a `TextLink` with an arrow before its words,
 *  the arrow inside the link, so the two are one target. The arrow is the
 *  icon, never the character, and says nothing a screen reader needs. */
export function BackLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <TextLink href={href} className="inline-flex items-center gap-1">
      <ArrowLeft size={14} strokeWidth={1.75} aria-hidden className="shrink-0" />
      {children}
    </TextLink>
  )
}
