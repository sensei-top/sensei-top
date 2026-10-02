/** The brand's glyph: a spinning top seen from the side, leaning as it
 *  turns — a stem, a shallow cap, a gap where the band is, and a cone down
 *  to the point. Drawn in `currentColor`, so the caller's text colour paints
 *  it; decorative, since the name beside it (or `Wordmark`'s label) says
 *  what it is. `web/public/favicon.svg` carries the same geometry. */
export function BrandGlyph({ size = 24, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      aria-hidden
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className={`shrink-0 ${className}`}
    >
      <g fill="currentColor" transform="rotate(14 12 13)">
        <rect x="10.8" y="1" width="2.4" height="6.2" rx="1.2" />
        <path d="M3.2 10.9C3.2 8.3 7.1 6.5 12 6.5s8.8 1.8 8.8 4.4Z" />
        <path d="M3.7 12.9H20.3L13.1 22.1Q12 23.4 10.9 22.1Z" />
      </g>
    </svg>
  )
}
