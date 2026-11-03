import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { CopyPromptCard } from '../CopyPromptCard'
import { usePasteBrief } from '../hooks'

/** The break read's last tier: the prompt to write an exact plan from, when
 *  neither an exact nor a closest plan is stored. Saving needs both keys;
 *  without them the card only copies. */
export function BreakBriefPrompt({
  title,
  prompt,
  deckKey,
  archetypeKey,
  children,
}: {
  title: string
  prompt: string | null | undefined
  deckKey: string | null | undefined
  archetypeKey: string | null | undefined
  children?: ReactNode
}) {
  const { t } = useTranslation()
  const paste = usePasteBrief()
  return (
    <CopyPromptCard
      title={title}
      subtitle={t('matchups.sideboard.noPlanYet')}
      prompt={prompt}
      save={
        deckKey && archetypeKey
          ? (answer) => paste.mutateAsync({ key: deckKey, archetypeKey, answer })
          : undefined
      }
    >
      {children}
    </CopyPromptCard>
  )
}
