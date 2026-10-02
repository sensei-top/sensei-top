import type { ReactNode } from 'react'

/** A block of text too literal for prose (a prompt, a command, exported
 *  Markdown), set as a `pre` in the interface face, since there is no
 *  monospaced one, and wrapped so it never scrolls sideways: a long
 *  command with no space in it breaks inside the word rather than
 *  running past the card. `scroll` caps it at `max-h-64` with its own
 *  scrollbar (the prompt, the Markdown); without it the block is as tall
 *  as its text (the command). */
export function TextBlock({ scroll = false, children }: { scroll?: boolean; children: ReactNode }) {
  return (
    <pre
      className={`whitespace-pre-wrap break-words rounded-block border border-edge bg-plane p-3 font-sans text-caption text-ink2 ${
        scroll ? 'max-h-64 overflow-y-auto' : ''
      }`}
    >
      {children}
    </pre>
  )
}
