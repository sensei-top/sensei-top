import type { ReactNode } from 'react'
import { CHIP_MUTED_CLASS, CHIP_VARIANT_CLASS, type ChipVariant } from './chipStyles'

export type { ChipVariant }

// 22 px (the tag) and 26 px (the default) at comfortable density. A minimum,
// not a fixed height, so a long word that wraps at a narrow width grows the
// pill instead of spilling out of it.
const SIZE_CLASS = {
  sm: 'min-h-5.5 px-2',
  md: 'min-h-6.5 px-2.5',
} as const

/** A filled pill with no border. */
export function Chip({
  children,
  variant = 'neutral',
  size = 'md',
  emphasis = false,
  muted = false,
  title,
  className = '',
}: {
  children: ReactNode
  variant?: ChipVariant
  size?: keyof typeof SIZE_CLASS
  /** Bolder weight for a chip that is the primary fact on its row, not a
   *  secondary tag (e.g. a card just revealed, vs. one already struck through). */
  emphasis?: boolean
  /** Only with `neutral`: the same fill with the word in `text-muted`, for
   *  the lowest step of a scale (the severity `note`). */
  muted?: boolean
  title?: string
  className?: string
}) {
  const colour = muted && variant === 'neutral' ? CHIP_MUTED_CLASS : CHIP_VARIANT_CLASS[variant]
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-pill text-chip leading-tight ${
        emphasis ? 'font-bold' : 'font-semibold'
      } ${SIZE_CLASS[size]} ${colour} ${className}`}
    >
      {children}
    </span>
  )
}
