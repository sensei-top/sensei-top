import { createContext, type ReactNode, useContext } from 'react'
import type { components } from '../types/api'

export type RulesNote = components['schemas']['RulesNoteOut']

/** How a `[N<n>]` marker is drawn: `ai/notes/context.tsx` provides the
 *  renderer, `Prose` calls it. Here, not in `ui/`, since `ui/` may not
 *  import `ai/`. The default draws nothing: a marker nobody knows renders
 *  as nothing. */
export const NoteMarkerContext = createContext<(n: string) => ReactNode>(() => null)

export const RulesNotesContext = createContext<ReadonlyMap<string, RulesNote>>(new Map())

/** The note the prose cites as `[N<n>]`, or `undefined` when no
 *  `RulesNotesProvider` above knows it. Here, not in `context.tsx`, so that
 *  file exports only a component. */
export function useRulesNote(n: number | string): RulesNote | undefined {
  return useContext(RulesNotesContext).get(`N${n}`)
}
