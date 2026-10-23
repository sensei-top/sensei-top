import { Info } from 'lucide-react'
import { type ReactNode, useEffect, useId, useState } from 'react'

/** A short sentence about `children`, shown while the pointer is over them
 *  or they have keyboard focus, and closed by Escape until the next hover
 *  or focus. `children` become a focusable trigger described by the tip
 *  (`aria-describedby`), so pass text, never a control: a button or a link
 *  inside would be a second stop for the keyboard. The tip stays in the
 *  document while closed, so the description is read either way. The trigger draws a muted `Info` icon after
 *  `children`, so a caller passes no icon of its own. `align` is the edge of
 *  the trigger the tip hangs from: `'end'` for a trigger at the right of
 *  its container, so the tip opens leftward and is not cut off. */
export function Tooltip({
  tip,
  children,
  align = 'start',
}: {
  tip: string
  children: ReactNode
  align?: 'start' | 'end'
}) {
  const tipId = useId()
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const open = (hovered || focused) && !dismissed

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDismissed(true)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  return (
    // The pointer handlers sit on the wrapper, not the trigger, so the tip
    // stays open while the pointer moves onto it to read it.
    <span
      className="relative inline-flex"
      onPointerEnter={() => {
        setHovered(true)
        setDismissed(false)
      }}
      onPointerLeave={() => setHovered(false)}
    >
      <span
        tabIndex={0}
        aria-describedby={tipId}
        onFocus={(event) => {
          // Keyboard focus only: a click also focuses, and would pin the tip.
          if (!event.currentTarget.matches(':focus-visible')) return
          setFocused(true)
          setDismissed(false)
        }}
        onBlur={() => setFocused(false)}
        className="cursor-help underline decoration-muted decoration-dotted underline-offset-4"
      >
        {children}
        <Info aria-hidden className="ml-1 inline size-(--text-caption) align-middle text-muted" />
      </span>
      {/* The gap above the tip is padding, not margin, so the pointer
          crossing it is still inside the wrapper. */}
      <span id={tipId} role="tooltip" hidden={!open} className={`absolute top-full z-30 pt-1.5 ${align === 'end' ? 'right-0' : 'left-0'}`}>
        {/* text-left font-normal: a trigger in a <th> would pass the tip the header's alignment and weight. */}
        <span className="block w-max max-w-60 rounded-control text-left font-normal border border-edge-strong bg-surface3 px-3 py-2 text-caption text-ink shadow-lift">
          {tip}
        </span>
      </span>
    </span>
  )
}
