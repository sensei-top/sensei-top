import { useEffect, useId, useRef, type ReactNode } from 'react'

/** A question that waits for an answer: the native modal `dialog`, which
 *  holds focus while it is open and gives it back to what opened it. It
 *  opens only when `open` says so, never by itself. Escape, a press on the
 *  backdrop and the caller's buttons all end in the element's `close`
 *  event, where `onClose` is called once. `actions` are the buttons, the
 *  safe one first in the source and `primary`; the row draws it last on
 *  screen, at the right. It has no read-only form: it is an answer or
 *  nothing, and it never holds a form longer than three fields. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  actions,
}: {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  actions: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  // `showModal()` on an open dialog throws, and `close()` on a closed one
  // fires no event, so each is guarded by the element's own `open`.
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    else if (!open && dialog.open) dialog.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      // A click on the backdrop lands on the dialog itself, never on
      // anything inside it; the padding is the inner box's for that reason.
      onClick={(event) => {
        if (event.target === event.currentTarget) event.currentTarget.close()
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-card border border-edge bg-surface p-0 text-ink shadow-lift backdrop:bg-plane/70"
    >
      <div className="p-5">
        <h2 id={titleId} className="font-display text-title text-ink">
          {title}
        </h2>
        <div className="mt-2 text-body text-ink2">{children}</div>
        <div className="mt-5 flex flex-row-reverse flex-wrap justify-start gap-2">{actions}</div>
      </div>
    </dialog>
  )
}
