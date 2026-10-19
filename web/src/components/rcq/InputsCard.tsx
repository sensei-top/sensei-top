import { Check } from 'lucide-react'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { archetypeName } from '../../lib/decks'
import { splitOptions, type ExpectedOption, type RcqInputs } from '../../lib/rcq'
import { formatPercent } from '../../lib/format'
import { Card, Select } from '../ui'

/** The 75 as the player will register it: a text box the size of a list,
 *  in the house box (`Field`'s look, `docs/design-system.md`'s "Form
 *  controls"), since `Field` is one line. */
function DecklistBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useTranslation()
  const id = useId()
  const hintId = `${id}-hint`
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-caption font-medium text-ink2">
        {t('rcq.inputs.yourList')}
      </label>
      <textarea
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={16}
        spellCheck={false}
        autoComplete="off"
        aria-describedby={hintId}
        className="min-h-[44px] w-full rounded-control border border-edge bg-surface px-3 py-2 text-body text-ink placeholder:text-muted"
      />
      <p id={hintId} className="text-caption text-muted">
        {t('rcq.inputs.listHint')}
      </p>
    </div>
  )
}

/** One archetype the player may expect, pressed or not. A pressed chip
 *  draws a check before its name and a stronger fill, and says its state
 *  to a screen reader (`aria-pressed`): the mark, not the colour alone,
 *  is what shows it. */
function ExpectedChip({
  option,
  pressed,
  onToggle,
}: {
  option: ExpectedOption
  pressed: boolean
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onToggle}
      className={`min-h-[44px] rounded-pill px-3 text-caption font-medium transition-chrome ${
        pressed ? 'bg-surface3 text-ink' : 'bg-surface2 text-ink2 hover:text-ink'
      }`}
    >
      {pressed && <Check size={14} strokeWidth={2} aria-hidden className="mr-1 inline-block shrink-0 align-[-2px]" />}
      {option.label}
      {option.share != null && <span className="ml-1.5 text-muted tabular-nums">{formatPercent(option.share)}</span>}
    </button>
  )
}

/** What the guide is written for: the 75, the archetypes the player
 *  expects at the store (picked from the field's own keys, never typed),
 *  and, only when the 75 could not be classified or the player already
 *  chose, which archetype it is. With `formatUnknown` (the deck has no
 *  tournament format) there is no field to pick from, so the chip block is
 *  not drawn at all: no chips, no pending line, no empty line. */
export function InputsCard({
  inputs,
  onChange,
  options,
  shareNote,
  optionsPending,
  formatUnknown,
  showOwnPicker,
  names,
}: {
  inputs: RcqInputs
  onChange: (inputs: RcqInputs) => void
  options: ExpectedOption[]
  /** The sentence that says what the chips' share is of. */
  shareNote: string | null
  optionsPending: boolean
  formatUnknown: boolean
  showOwnPicker: boolean
  /** Names the preview gave the archetypes expected, by key: the label of
   *  a chip for a key the field's options no longer hold. */
  names: Record<string, string>
}) {
  const { t } = useTranslation()
  const expected = new Set(inputs.expected)
  // A key kept from before that the options no longer hold still gets a
  // chip, after the field's, so it can be unpicked.
  const offered = new Set(options.map((option) => option.key))
  const kept = (key: string): ExpectedOption => ({ key, label: archetypeName(names[key] ?? key), share: null })
  const missing = inputs.expected.filter((key) => !offered.has(key)).map(kept)
  // The main field is always shown; the rest of it behind "Other", except
  // a pick, which stays in view so it can be unpicked.
  const [showOther, setShowOther] = useState(false)
  const { main, other } = splitOptions(options)
  const chips = [...main, ...other.filter((option) => showOther || expected.has(option.key)), ...missing]
  const hiddenOther = other.filter((option) => !expected.has(option.key)).length
  const ownOptions = [
    ...options,
    ...(inputs.own != null && !offered.has(inputs.own) ? [kept(inputs.own)] : []),
  ].map((option) => ({ value: option.key, label: option.label }))
  const toggle = (key: string) =>
    onChange({
      ...inputs,
      expected: expected.has(key) ? inputs.expected.filter((each) => each !== key) : [...inputs.expected, key],
    })

  return (
    <Card title={t('rcq.inputs.title')} subtitle={t('rcq.inputs.subtitle')}>
      <div className="space-y-5">
        <DecklistBox value={inputs.decklist} onChange={(decklist) => onChange({ ...inputs, decklist })} />

        {!formatUnknown && (
          <div className="space-y-2">
            <h3 className="text-caption font-medium text-ink2">{t('rcq.inputs.expectedTitle')}</h3>
            <p className="text-caption text-muted">
              {t('rcq.inputs.expectedHint')}
              {shareNote ? ` ${shareNote}` : ''}
            </p>
            {optionsPending && <p className="text-caption text-muted">{t('rcq.inputs.reading')}</p>}
            {!optionsPending && options.length === 0 && (
              <p className="text-caption text-muted">{t('rcq.inputs.noArchetype')}</p>
            )}
            {chips.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {chips.map((option) => (
                  <ExpectedChip
                    key={option.key}
                    option={option}
                    pressed={expected.has(option.key)}
                    onToggle={() => toggle(option.key)}
                  />
                ))}
                {hiddenOther > 0 && (
                  <button
                    type="button"
                    aria-expanded={showOther}
                    onClick={() => setShowOther(!showOther)}
                    className="min-h-[44px] rounded-pill border border-edge px-3 text-caption font-medium text-ink2 transition-chrome hover:text-ink"
                  >
                    {showOther ? t('rcq.inputs.fewer') : t('rcq.inputs.other', { n: hiddenOther })}
                  </button>
                )}
              </div>
            )}
          </div>
        )}

        {showOwnPicker && (
          <Select
            label={t('rcq.inputs.ownLabel')}
            placement="above"
            value={inputs.own ?? ''}
            options={ownOptions}
            onChange={(own) => onChange({ ...inputs, own: own === '' ? null : own })}
          >
            <option value="">{t('rcq.inputs.notChosen')}</option>
          </Select>
        )}
      </div>
    </Card>
  )
}
