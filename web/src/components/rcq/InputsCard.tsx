import { useId } from 'react'
import type { ExpectedOption, RcqInputs } from '../../lib/rcq'
import { formatPercent } from '../../lib/time'
import { Card, Select } from '../ui'

/** The 75 as the player will register it: a text box the size of a list,
 *  in the house box (`Field`'s look, `docs/design-system.md`'s "Form
 *  controls"), since `Field` is one line. */
function DecklistBox({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const id = useId()
  const hintId = `${id}-hint`
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-caption font-medium text-ink2">
        Your 75
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
        Arena's export, MTGO's or a plain list: a count and a name a line, the sideboard after a blank line or under
        "Sideboard".
      </p>
    </div>
  )
}

/** One archetype the player may expect, pressed or not. The word says
 *  which as much as the fill: a pressed chip reads its state to a screen
 *  reader (`aria-pressed`). */
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
      {option.label}
      {option.share != null && <span className="ml-1.5 text-muted tabular-nums">{formatPercent(option.share)}%</span>}
    </button>
  )
}

/** What the guide is written for: the 75, the archetypes the player
 *  expects at the store (picked from the field's own keys, never typed),
 *  and, only when the 75 could not be classified or the player already
 *  chose, which archetype it is. */
export function InputsCard({
  inputs,
  onChange,
  options,
  shareNote,
  optionsPending,
  showOwnPicker,
}: {
  inputs: RcqInputs
  onChange: (inputs: RcqInputs) => void
  options: ExpectedOption[]
  /** The sentence that says what the chips' share is of. */
  shareNote: string | null
  optionsPending: boolean
  showOwnPicker: boolean
}) {
  const expected = new Set(inputs.expected)
  const toggle = (key: string) =>
    onChange({
      ...inputs,
      expected: expected.has(key) ? inputs.expected.filter((each) => each !== key) : [...inputs.expected, key],
    })

  return (
    <Card title="Your list and the store" subtitle="Kept on this computer for this deck, as you leave them.">
      <div className="space-y-5">
        <DecklistBox value={inputs.decklist} onChange={(decklist) => onChange({ ...inputs, decklist })} />

        <div className="space-y-2">
          <h3 className="text-caption font-medium text-ink2">Expected at the store</h3>
          <p className="text-caption text-muted">
            Each one you pick gets its own plan. The field's numbers still lead.
            {shareNote ? ` ${shareNote}` : ''}
          </p>
          {optionsPending ? (
            <p className="text-caption text-muted">Reading the field…</p>
          ) : options.length === 0 ? (
            <p className="text-caption text-muted">The tournament corpus names no archetype yet.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {options.map((option) => (
                <ExpectedChip
                  key={option.key}
                  option={option}
                  pressed={expected.has(option.key)}
                  onToggle={() => toggle(option.key)}
                />
              ))}
            </div>
          )}
        </div>

        {showOwnPicker && (
          <Select
            label="Your 75 is"
            placement="above"
            value={inputs.own ?? ''}
            options={options.map((option) => ({ value: option.key, label: option.label }))}
            onChange={(own) => onChange({ ...inputs, own: own === '' ? null : own })}
          >
            <option value="">Not chosen</option>
          </Select>
        )}
      </div>
    </Card>
  )
}
