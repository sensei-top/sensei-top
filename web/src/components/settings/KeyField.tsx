import { useState } from 'react'
import type { Saved } from '../../bridge'
import { failureOf, settle } from '../../lib/settings'
import { Button, Dialog, Field } from '../ui'
import { SaveButton } from './SaveButton'

/** A key's block in a card: whether a key is set, and the way to set,
 *  replace or remove one. What is typed lives in this block's own state
 *  alone, is sent only through `onSet`, and is cleared when that answers
 *  and when "Cancel" is pressed. Removing asks first, in a dialog
 *  whose safe button is the primary one. The page is only ever told
 *  whether a key is set, never the key. With no shell there is no `onSet`:
 *  the block says a key is set when one is, and otherwise shows the field's
 *  label and nothing to type into. */
export function KeyField({
  set,
  onSet,
  removeBody,
}: {
  set: boolean
  /** `null` removes the key. */
  onSet?: (key: string | null) => Promise<Saved>
  /** The dialog's sentence: what removing this key changes. */
  removeBody: string
}) {
  const [typed, setTyped] = useState('')
  const [replacing, setReplacing] = useState(false)
  const [asking, setAsking] = useState(false)
  const [removing, setRemoving] = useState(false)
  const [error, setError] = useState<string | undefined>(undefined)

  if (!onSet) {
    return set ? <p className="text-body text-ink">A key is set.</p> : <Field label="Key" value="" type="password" />
  }

  const save = async (): Promise<boolean> => {
    const key = typed.trim()
    if (key === '') return false
    setError(undefined)
    const sentence = failureOf(await settle(onSet(key)))
    // Cleared whatever the answer: React mirrors an input's value into its
    // `value` attribute, and a key stays in no attribute after a save.
    setTyped('')
    if (sentence !== null) {
      setError(sentence)
      return false
    }
    setReplacing(false)
    return true
  }

  const cancel = () => {
    setTyped('')
    setError(undefined)
    setReplacing(false)
  }

  const remove = async () => {
    setRemoving(true)
    setError(undefined)
    const sentence = failureOf(await settle(onSet(null)))
    setRemoving(false)
    if (sentence !== null) setError(sentence)
  }

  if (!set || replacing) {
    return (
      <div className="space-y-3">
        <Field
          label="Key"
          type="password"
          autoComplete="off"
          value={typed}
          onChange={setTyped}
          placeholder="Paste a key"
          hint="Shown only while you type it. Kept on this computer."
          error={error}
        />
        <div className="flex flex-wrap items-center gap-2">
          <SaveButton dirty={typed.trim() !== ''} onSave={save} label="Save the key" savedLabel={null} />
          {replacing && (
            <Button variant="quiet" className="min-h-[44px]" onClick={cancel}>
              Cancel
            </Button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-body text-ink">A key is set.</p>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="quiet"
          className="min-h-[44px]"
          disabled={removing}
          onClick={() => {
            setError(undefined)
            setReplacing(true)
          }}
        >
          Replace the key
        </Button>
        <Button
          variant="quiet"
          className="min-h-[44px]"
          disabled={removing}
          aria-haspopup="dialog"
          onClick={() => setAsking(true)}
        >
          Remove the key
        </Button>
      </div>
      {error && <p className="break-words text-caption text-loss">{error}</p>}
      <Dialog
        open={asking}
        onClose={() => setAsking(false)}
        title="Remove the key?"
        actions={
          <>
            <Button variant="primary" className="min-h-[44px]" onClick={() => setAsking(false)}>
              Keep it
            </Button>
            <Button
              className="min-h-[44px]"
              onClick={() => {
                setAsking(false)
                void remove()
              }}
            >
              Remove the key
            </Button>
          </>
        }
      >
        <p>{removeBody}</p>
      </Dialog>
    </div>
  )
}
