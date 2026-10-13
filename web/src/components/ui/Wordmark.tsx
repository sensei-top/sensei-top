import { PRODUCT_NAME } from '../../shell/places'
import { BrandGlyph } from './BrandGlyph'

const SIZE = {
  sm: { glyph: 20, text: 'text-lead font-bold' },
  // `title` carries the display face's 700 itself (index.css).
  md: { glyph: 24, text: 'text-title' },
} as const

/** The glyph in the accent beside the name in the display face at 700.
 *  `glyphOnly` drops the name from sight and keeps it as the label. */
export function Wordmark({ size = 'md', glyphOnly = false }: { size?: 'sm' | 'md'; glyphOnly?: boolean }) {
  const { glyph, text } = SIZE[size]
  if (glyphOnly) {
    return (
      <span role="img" aria-label={PRODUCT_NAME} className="inline-flex text-accent">
        <BrandGlyph size={glyph} />
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-2">
      <BrandGlyph size={glyph} className="text-accent" />
      <span className={`font-display ${text} whitespace-nowrap text-ink`}>{PRODUCT_NAME}</span>
    </span>
  )
}
