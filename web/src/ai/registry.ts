import { useAiFeatures } from '../shell/aiFeatures'
import { CopyPromptBody, CopyPromptCard } from './CopyPromptCard'
import { GenerateCard } from './GenerateCard'
import { CoachView } from './coach/CoachView'
import { BreakBriefPrompt } from './brief/BreakBriefPrompt'
import { BoardPlan, BriefProvenance, MatchupBriefCard, PlayAroundList } from './brief/MatchupBriefCard'
import { PairingBrief } from './brief/PairingBrief'
import { CoveragePrompt } from './guide/CoveragePrompt'
import { LeaksNarrativeCard } from './guide/LeaksNarrativeCard'
import { RcqWrite } from './guide/RcqWrite'
import { ReportNarrativeCard } from './report/ReportNarrativeCard'
import { NarrativeAndExport } from './guide/WriteAndExport'
import { WritingSection, WritingStatus } from './settings/WritingSection'

const SURFACES = {
  GenerateCard,
  CopyPromptCard,
  CopyPromptBody,
  CoachView,
  MatchupBriefCard,
  BoardPlan,
  PlayAroundList,
  BriefProvenance,
  BreakBriefPrompt,
  CoveragePrompt,
  PairingBrief,
  LeaksNarrativeCard,
  RcqWrite,
  ReportNarrativeCard,
  NarrativeAndExport,
  WritingSection,
  WritingStatus,
} as const

/** The AI surfaces a page outside `ai/` may draw. */
export type AiRegistry = typeof SURFACES

/** The only way into `ai/` from outside it; `.oxlintrc.json` refuses any
 *  other import of an `ai/` module. A caller calls this hook once, at the
 *  top of the component like any hook, and draws `ai.GenerateCard` and the
 *  rest from what it returns. `null` means AI features are off: the caller
 *  draws nothing of its AI part, its heading and any sentence about it
 *  included. */
export function useAi(): AiRegistry | null {
  const [on] = useAiFeatures()
  return on ? SURFACES : null
}
