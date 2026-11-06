import { Check } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Contribute } from '../bridge'
import { useShell } from '../bridge'
import { ageBox, canPress, hintsFor, isPressed, pressAnswer, savedAnswer } from '../lib/contribute'
import { POLICY_VERSION } from '../lib/policy'

const DISCLOSURE = ['noAccount', 'what', 'where', 'final', 'stop'] as const

/** The five sentences every place that asks "Help build the stats" says. */
export function ContributeDisclosure() {
  const { t } = useTranslation()
  return (
    <div className="space-y-1 text-body text-ink2">
      {DISCLOSURE.map((line) => (
        <p key={line}>{t(`contribute.disclosure.${line}`)}</p>
      ))}
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
      <label className="flex items-start gap-3 text-body text-ink">
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
 *  ticked. `stored` is the shell's answer, `picked` this run's saved press;
 *  `waiting` is Go to Home waiting on this or the AI question. The save goes
 *  through the shell's `contribSet`. */
export function ContributeQuestion({
  stored,
  picked,
  waiting,
  onPicked,
  waitingHint,
  showHeading = true,
}: {
  stored: Contribute | null
  picked: boolean | null
  waiting: boolean
  onPicked: (yes: boolean) => void
  /** The hint shown while `waiting`; Welcome's by default. */
  waitingHint?: string
  /** Whether the question draws its own heading. */
  showHeading?: boolean
}) {
  const { t } = useTranslation()
  const shell = useShell()
  const [age, setAge] = useState(false)
  const [saving, setSaving] = useState<boolean | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const saved = savedAnswer(stored, picked)

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
      <ContributeDisclosure />
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
              onClick={() => void choose(yes)}
            />
          )
        })}
      </div>
      {hints.map((hint) => (
        <p key={hint} className="text-caption text-muted">
          {hint === 'age' ? t('contribute.hint.age') : waitingHint ?? t('contribute.hint.waitsWelcome')}
        </p>
      ))}
      {failure && (
        <p role="alert" className="break-words text-caption text-loss">
          {failure}
        </p>
      )}
    </div>
  )
}

/** A button of a choice: the one pressed has a check and the accent border. */
export function ChoiceTile({
  pressed,
  disabled,
  label,
  className,
  onClick,
}: {
  pressed: boolean
  disabled: boolean
  label: string
  className: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={`flex items-center justify-center gap-2 rounded-control border text-body font-medium transition-chrome disabled:opacity-60 ${className} ${
        pressed
          ? 'border-accent bg-surface3 text-ink'
          : 'border-edge bg-surface2 text-ink2 hover:border-edge-strong hover:text-ink'
      }`}
    >
      {pressed && <Check size={16} strokeWidth={2.25} aria-hidden className="shrink-0 text-accent" />}
      {label}
    </button>
  )
}
