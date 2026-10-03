import type { Allowance } from '../../bridge'
import {
  ALLOWANCE_EACH,
  allowanceSentence,
  allowanceUsed,
  kindsNamed,
  partLeft,
  percentLeft,
  startsAgainSentence,
} from '../../lib/plan'
import { Meter, SectionLabel } from '../ui'

/** The plan's allowance, the same block in every card that shows one: its
 *  label, the meter in the accent with the percentage left beside it, the
 *  reports it still writes as alternatives, and when it starts again. Used
 *  up, one sentence says so and that every report still gives its prompt.
 *  On a trial the label is the trial's and nothing says it starts again,
 *  since a trial's does not. Drawn in the plan's card on a trial, a running
 *  plan and a failed payment. */
export function AllowanceMeter({ allowance, onTrial, now }: { allowance: Allowance; onTrial: boolean; now: number }) {
  const used = allowanceUsed(allowance.left)
  const fraction = partLeft(allowance.used)
  const again = onTrial ? null : startsAgainSentence(allowance.startsAgain, now)
  return (
    <div className="space-y-2">
      <SectionLabel>{onTrial ? "The trial's allowance" : "This month's allowance"}</SectionLabel>
      <div className="flex items-center gap-3">
        <div
          role="meter"
          aria-label="Allowance left"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(fraction * 100)}
          className="min-w-0 flex-1"
        >
          <Meter fraction={fraction} color="accent" />
        </div>
        <span className="shrink-0 text-caption text-ink2 tabular-nums">{percentLeft(allowance.used)}</span>
      </div>
      <p className="text-body text-ink2">{allowanceSentence(allowance.left)}</p>
      {!used && kindsNamed(allowance.left) > 1 && <p className="text-caption text-muted">{ALLOWANCE_EACH}</p>}
      {again && <p className="text-caption text-muted">{again}</p>}
    </div>
  )
}
