import { Check } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Contribute } from '../bridge'
import { useShell } from '../bridge'
import { MoreAbout } from './ui'
import { ageBox, canPress, hintsFor, isPressed, pressAnswer, savedAnswer } from '../lib/contribute'
import { POLICY_VERSION } from '../lib/policy'

/** The five sentences every place that asks "Help build the stats" says:
 *  what it is and that a sent game can't be deleted on the page, where the
 *  pool is and how to stop under More about this. `foldNoAccount` moves the
 *  no-account line under the fold too, for a page that names no account. */
export function ContributeDisclosure({ foldNoAccount = false }: { foldNoAccount?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="max-w-prose space-y-1 text-body text-ink2">
      {!foldNoAccount && <p>{t('contribute.disclosure.noAccount')}</p>}
      <p>{t('contribute.disclosure.what')}</p>
      <p>{t('contribute.disclosure.final')}</p>
      <MoreAbout>
        {foldNoAccount && <p>{t('contribute.disclosure.noAccount')}</p>}
        <p>{t('contribute.disclosure.where')}</p>
        <p>{t('contribute.disclosure.stop')}</p>
      </MoreAbout>
    </div>
  )
}

/** The age box of its own, above the answers: unticked, and locked once a
 *  yes is saved. */
export function ContributeAge({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean
  disabled: boolean
  onChange: (on: boolean) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="space-y-1">
      <label className="flex max-w-prose items-start gap-3 text-body text-ink">
        <input
          type="checkbox"
          className="mt-1 size-4 shrink-0 accent-accent"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{t('contribute.age.label')}</span>
      </label>
      <p className="pl-7 text-caption text-muted">{t('contribute.age.small')}</p>
    </div>
  )
}

/** "Help build the stats" on Welcome's last step. Two buttons, neither
 *  pressed until the answer is saved; the yes is off until the age box is
 *  ticked, and names the age hint as its description. `stored` is the
 *  shell's answer, `picked` this run's saved press; `waiting` is Go to Home
 *  waiting on this or the AI question. The hints are one line, so the age
 *  and the wait don't stack. The save goes through the shell's
 *  `contribSet`. */
export function ContributeQuestion({
  stored,
  picked,
  waiting,
  onPicked,
  waitingHint,
  showHeading = true,
  foldNoAccount = false,
}: {
  stored: Contribute | null
  picked: boolean | null
  waiting: boolean
  onPicked: (yes: boolean) => void
  /** The hint shown while `waiting`; Welcome's by default. */
  waitingHint?: string
  /** Whether the question draws its own heading. */
  showHeading?: boolean
  /** Whether the no-account line folds under More about this. */
  foldNoAccount?: boolean
}) {
  const { t } = useTranslation()
  const shell = useShell()
  const [age, setAge] = useState(false)
  const [saving, setSaving] = useState<boolean | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const saved = savedAnswer(stored, picked)
  const hintId = useId()

  const choose = async (yes: boolean) => {
    setSaving(yes)
    setFailure(null)
    const result = await pressAnswer(yes, age, stored, saved, POLICY_VERSION, shell?.contribSet, t)
    setSaving(null)
    // `needAge` cannot come back: the yes is off until the box is ticked.
    if (result.kind === 'failed') setFailure(result.line)
    else if (result.kind === 'saved') onPicked(result.yes)
  }

  const options = [
    { yes: true, label: t('contribute.answer.yes') },
    { yes: false, label: t('contribute.answer.no') },
  ]
  const box = ageBox(age, saved, saving !== null)
  const hints = hintsFor(box.checked, saved, waiting)
  return (
    <div className="space-y-3">
      {showHeading && <h3 className="text-body font-medium text-ink">{t('contribute.heading')}</h3>}
      <ContributeDisclosure foldNoAccount={foldNoAccount} />
      <ContributeAge checked={box.checked} disabled={box.disabled} onChange={setAge} />
      <div className="flex flex-wrap gap-3">
        {options.map(({ yes, label }) => {
          return (
            <ChoiceTile
              key={String(yes)}
              pressed={isPressed(saved, yes)}
              disabled={!canPress(yes, box.checked, saving !== null)}
              label={label}
              className="min-h-[44px] px-4 py-2"
              describedBy={yes && hints.includes('age') ? hintId : undefined}
              onClick={() => void choose(yes)}
            />
          )
        })}
      </div>
      {hints.length > 0 && (
        <p id={hintId} className="max-w-prose text-caption text-muted">
          {hints
            .map((hint) =>
              hint === 'age' ? t('contribute.hint.age') : (waitingHint ?? t('contribute.hint.waitsWelcome')),
            )
            .join(' ')}
        </p>
      )}
      {failure && (
        <p role="alert" className="break-words text-caption text-loss">
          {failure}
        </p>
      )}
    </div>
  )
}

/** A button of a choice: the one pressed has a check and the accent border.
 *  Off, it is the same box at half strength with no hover, as every disabled
 *  control is; `describedBy` names the line that says why. */
export function ChoiceTile({
  pressed,
  disabled,
  label,
  className,
  describedBy,
  onClick,
}: {
  pressed: boolean
  disabled: boolean
  label: string
  className: string
  describedBy?: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      aria-describedby={describedBy}
      disabled={disabled}
      onClick={onClick}
      className={`flex items-center justify-center gap-2 rounded-control border text-body font-medium transition-chrome disabled:cursor-not-allowed disabled:opacity-50 ${className} ${
        pressed
          ? 'border-accent bg-surface3 text-ink'
          : 'border-edge bg-surface2 text-ink2 enabled:hover:border-edge-strong enabled:hover:text-ink'
      }`}
    >
      {pressed && <Check size={16} strokeWidth={2.25} aria-hidden className="shrink-0 text-accent" />}
      {label}
    </button>
  )
}
