import { useState } from 'react'
import type { Saved, SharedDraft } from '../../bridge'
import { answerOf, pressFailure } from '../../lib/plan'
import { ago, useNow } from '../../lib/time'
import { PressButton } from '../settings/SaveButton'

const NOT_REMOVED = 'The server did not answer. The draft is still shared.'

/** A finished draft's receipt, one line on its page: waiting to be sent;
 *  shared and when, with "Undo", which says "Removing" while in flight and
 *  then reads as removed; or removed. A failed undo says so under the line.
 *  A shared draft whose time cannot be read says it was shared, with no
 *  time. A draft never shared draws nothing. Drawn only where the shell offers sharing; with no `unshare`,
 *  a shared draft has nothing to press. */
export function DraftReceipt({ shared, unshare }: { shared: SharedDraft; unshare?: () => Promise<Saved> }) {
  const now = useNow()
  const [removed, setRemoved] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const undo = async (): Promise<boolean> => {
    if (!unshare) return false
    setFailure(null)
    const sentence = pressFailure(await answerOf(unshare()), NOT_REMOVED)
    if (sentence !== null) {
      setFailure(sentence)
      return false
    }
    setRemoved(true)
    return true
  }

  if (removed || shared.state === 'removed') {
    return <p className="text-caption text-ink2">This draft was removed from the server.</p>
  }
  if (shared.state === 'waiting') {
    return <p className="text-caption text-ink2">This draft is sent once its games are over.</p>
  }
  if (shared.state !== 'shared') return null
  const when = ago(shared.at, now)

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-x-3">
        <p className="text-caption text-ink2">
          {when === null ? 'This draft was shared.' : `This draft was shared ${when}.`}
        </p>
        {unshare && (
          <PressButton variant="quiet" label="Undo" workingLabel="Removing" doneLabel={null} onPress={undo} />
        )}
      </div>
      {failure && <p className="break-words text-caption text-loss">{failure}</p>}
    </div>
  )
}
