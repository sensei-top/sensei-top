import { type ReactNode, useCallback, useMemo } from 'react'
import { NoteMarkerContext, type RulesNote, RulesNotesContext } from '../../lib/noteMarker'
import { RulesNoteChip } from './RulesNoteChip'

export type { RulesNote }

/** The notes a narrative's GET returned, for every `Prose` below it: a
 *  `[N<n>]` there draws that note's chip, and nothing when `notes` does
 *  not hold it. `Prose` lives in `ui/`, which may not import `ai/`, so the
 *  provider hands it the renderer instead of it asking for the notes. */
export function RulesNotesProvider({
  notes,
  children,
}: {
  notes: readonly RulesNote[] | null | undefined
  children: ReactNode
}) {
  const byMarker = useMemo(() => new Map((notes ?? []).map((note) => [note.marker, note])), [notes])
  const render = useCallback(
    (n: string): ReactNode => {
      const note = byMarker.get(`N${n}`)
      return note ? <RulesNoteChip note={note} /> : null
    },
    [byMarker],
  )
  return (
    <RulesNotesContext.Provider value={byMarker}>
      <NoteMarkerContext.Provider value={render}>{children}</NoteMarkerContext.Provider>
    </RulesNotesContext.Provider>
  )
}
