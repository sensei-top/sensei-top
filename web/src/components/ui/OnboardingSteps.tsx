import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { Chip } from './Chip'

export type OnboardingStepState = 'done' | 'next' | 'later'

export type OnboardingStep = {
  title: string
  state: OnboardingStepState
  /** What to do about it. Shown only while the step is next. */
  detail?: ReactNode
}

const STATE_WORD: Record<OnboardingStepState, string> = {
  done: 'Done',
  next: 'Next',
  later: 'Later',
}

/** A short run of steps toward a first result, each done, next or later,
 *  and saying so in words. The number's disc reinforces the word: a check
 *  once done, the accent on the one that is next (the one thing to do
 *  now), muted after it. Only the next step says what to do. */
export function OnboardingSteps({ steps }: { steps: OnboardingStep[] }) {
  return (
    <ol className="space-y-2">
      {steps.map((step, index) => {
        const next = step.state === 'next'
        return (
          <li
            key={step.title}
            aria-current={next ? 'step' : undefined}
            className={`flex gap-3 rounded-block px-4 py-3 ${next ? 'bg-surface2' : ''}`}
          >
            <span
              aria-hidden
              className={`flex size-7 shrink-0 items-center justify-center rounded-pill font-display text-caption font-extrabold ${
                step.state === 'done'
                  ? 'bg-surface3 text-ink'
                  : next
                    ? 'bg-accent text-on-accent'
                    : 'bg-surface3 text-muted'
              }`}
            >
              {step.state === 'done' ? <Check size={16} strokeWidth={2.25} /> : index + 1}
            </span>
            <div className="min-w-0 flex-1 space-y-1.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className={`text-body font-semibold ${step.state === 'later' ? 'text-ink2' : 'text-ink'}`}>
                  {step.title}
                </span>
                <Chip size="sm" variant={next ? 'accent' : 'neutral'} muted={step.state === 'later'}>
                  {STATE_WORD[step.state]}
                </Chip>
              </div>
              {next && step.detail && <div className="text-body text-ink2">{step.detail}</div>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
