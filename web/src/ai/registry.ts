import { CopyPromptBody, CopyPromptCard } from './CopyPromptCard'
import { GenerateCard } from './GenerateCard'

const SURFACES = { GenerateCard, CopyPromptCard, CopyPromptBody } as const

/** The AI surfaces a page outside `ai/` may draw. */
export type AiRegistry = typeof SURFACES

/** The only way into `ai/` from outside it; `.oxlintrc.json` refuses any
 *  other import of an `ai/` module. A caller calls this hook once, at the
 *  top of the component like any hook, and draws `ai.GenerateCard` and the
 *  rest from what it returns. `null` means AI features are off: the caller
 *  draws nothing of its AI part, its heading and any sentence about it
 *  included. Until the switch exists it never returns `null`, so a caller
 *  must still handle it. */
export function useAi(): AiRegistry | null {
  return SURFACES
}
