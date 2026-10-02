import type { AnchorHTMLAttributes, ButtonHTMLAttributes, Ref } from 'react'
import { Link } from 'react-router'

export type ButtonVariant = 'primary' | 'secondary' | 'quiet'
export type ButtonSize = 'sm' | 'md'

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-on-accent hover:bg-accent/90 disabled:hover:bg-accent',
  secondary: 'bg-surface3 text-ink hover:bg-line2 disabled:hover:bg-surface3',
  quiet: 'text-ink2 hover:bg-surface2 hover:text-ink disabled:hover:bg-transparent',
}

// 40 and 32 px high at comfortable density; the spacing scale carries both
// down with the rest of a compact page.
const SIZE_CLASS: Record<ButtonSize, string> = {
  sm: 'h-8 px-3',
  md: 'h-10 px-4',
}

const ICON_SIZE_CLASS: Record<ButtonSize, string> = {
  sm: 'size-8',
  md: 'size-10',
}

type Look = {
  variant?: ButtonVariant
  size?: ButtonSize
  className?: string
}

/** An icon-only button has no text of its own, so its name is required: the
 *  type refuses `iconOnly` without an `aria-label`. */
type Label = { iconOnly: true; 'aria-label': string } | { iconOnly?: false; 'aria-label'?: string }

type AsButton = Look &
  Label &
  Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'className'> & {
    href?: undefined
    ref?: Ref<HTMLButtonElement>
  }

type AsLink = Look &
  Label &
  Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'aria-label' | 'className' | 'href'> & {
    /** Renders a link with the same look: the router's `Link` for a place
     *  in the app (an `href` that begins with a single `/`), an `<a>` for
     *  anything else. */
    href: string
    ref?: Ref<HTMLAnchorElement>
  }

export type ButtonProps = AsButton | AsLink

function buttonClass({ variant = 'secondary', size = 'md', iconOnly, className = '' }: Look & { iconOnly?: boolean }) {
  return `inline-flex shrink-0 items-center justify-center gap-1.5 rounded-pill text-caption font-semibold whitespace-nowrap transition-chrome disabled:cursor-not-allowed disabled:opacity-50 ${
    iconOnly ? ICON_SIZE_CLASS[size] : SIZE_CLASS[size]
  } ${VARIANT_CLASS[variant]} ${className}`
}

/** The one button primitive, a pill. `primary` is for the one call to action
 *  a card has, `secondary` for any other action, `quiet` for a text-only
 *  disclosure toggle or a control that sits on something else. Text carries
 *  the meaning; the fill reinforces it. With `href` it renders a link with
 *  the same look (the router's `Link` when the `href` is a place in the
 *  app, so following it never reloads the page), and `iconOnly` makes it
 *  round. Focus is the page's one
 *  `:focus-visible` ring, never a class of its own. `ref` reaches the element
 *  itself: `OpponentDeckLabel`'s picker anchors a portalled popover off the
 *  button's own bounding rect. */
export function Button(props: ButtonProps) {
  if (props.href !== undefined) {
    const { variant, size, iconOnly, className, ref, href, ...rest } = props
    const look = buttonClass({ variant, size, iconOnly, className })
    // `//host` is protocol-relative, another site, not a place in the app.
    if (href.startsWith('/') && !href.startsWith('//')) {
      return <Link ref={ref} to={href} {...rest} className={look} />
    }
    return <a ref={ref} href={href} {...rest} className={look} />
  }
  const { variant, size, iconOnly, className, ref, ...rest } = props
  return <button ref={ref} {...rest} className={buttonClass({ variant, size, iconOnly, className })} />
}
