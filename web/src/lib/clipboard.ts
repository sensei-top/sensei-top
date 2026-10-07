import { useEffect, useRef, useState } from 'react'

/** Whether a copy was made in the last two seconds, and the function
 *  that makes one. A refused copy stays silent: the button's label is
 *  the only feedback either way. The timer is cleared when the component
 *  leaves the page, so it never fires after that. */
export function useCopied(): { copied: boolean; copy: (text: string) => void } {
  const [copied, setCopied] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const left = useRef(false)

  useEffect(
    () => () => {
      left.current = true
      clearTimeout(timer.current)
    },
    [],
  )

  const copy = (text: string) => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        if (left.current) return
        setCopied(true)
        clearTimeout(timer.current)
        timer.current = setTimeout(() => setCopied(false), 2000)
      })
      .catch(() => {})
  }

  return { copied, copy }
}
