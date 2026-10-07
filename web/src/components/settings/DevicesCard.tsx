import { useState } from 'react'
import type { Device, Saved } from '../../bridge'
import { answerOf, deviceLimitSentence, NOT_REMOVED, pressFailure } from '../../lib/plan'
import { ago } from '../../lib/time'
import { Button, Card, Dialog } from '../ui'

/** The computers the plan works on, one row each: its name, "This
 *  computer" on the one the page runs on and when the others were last
 *  used, and a way to remove each of the others, which asks first in a
 *  dialog whose safe button is the primary one; the row's button says
 *  "Removing" while the shell answers. One sentence says how many the plan
 *  works on at a time. Drawn under the plan's card while a plan runs: on a
 *  trial, a running plan and a failed payment. With no `removeDevice` the
 *  rows have nothing to press. */
export function DevicesCard({
  devices,
  limit,
  removeDevice,
  now,
}: {
  devices: Device[]
  limit: number
  removeDevice?: (id: string) => Promise<Saved>
  now: number
}) {
  // The computer the dialog asks about stays chosen after it closes, so
  // the dialog's title is never empty; `open` alone opens and closes it.
  const [chosen, setChosen] = useState<Device | null>(null)
  const [open, setOpen] = useState(false)
  const [removing, setRemoving] = useState<string | null>(null)
  const [failure, setFailure] = useState<{ id: string; sentence: string } | null>(null)

  const remove = async (id: string) => {
    if (!removeDevice) return
    setRemoving(id)
    setFailure(null)
    const sentence = pressFailure(await answerOf(removeDevice(id)), NOT_REMOVED)
    setRemoving(null)
    if (sentence !== null) setFailure({ id, sentence })
  }

  return (
    <Card title="Computers" subtitle={deviceLimitSentence(limit)} className="max-w-3xl">
      <ul className="divide-y divide-edge">
        {devices.map((device) => {
          const seen = device.here ? null : ago(device.seen, now)
          return (
            <li key={device.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-3 first:pt-0 last:pb-0">
              <div className="min-w-0 flex-1">
                <p className="break-words text-body text-ink">{device.name}</p>
                {device.here ? (
                  <p className="text-caption text-muted">This computer</p>
                ) : (
                  seen !== null && <p className="text-caption text-muted">{`Last used ${seen}`}</p>
                )}
                {failure?.id === device.id && (
                  <p className="break-words text-caption text-loss">{failure.sentence}</p>
                )}
              </div>
              {removeDevice && !device.here && (
                <Button
                  variant="quiet"
                  className="min-h-[44px]"
                  disabled={removing !== null}
                  aria-haspopup="dialog"
                  onClick={() => {
                    setChosen(device)
                    setOpen(true)
                  }}
                >
                  {removing === device.id ? 'Removing' : 'Remove'}
                </Button>
              )}
            </li>
          )
        })}
      </ul>
      {chosen && (
        <Dialog
          open={open}
          onClose={() => setOpen(false)}
          title={`Remove ${chosen.name}?`}
          actions={
            <>
              <Button variant="primary" className="min-h-[44px]" onClick={() => setOpen(false)}>
                Keep it
              </Button>
              <Button
                className="min-h-[44px]"
                onClick={() => {
                  setOpen(false)
                  void remove(chosen.id)
                }}
              >
                Remove the computer
              </Button>
            </>
          }
        >
          <p>The plan stops working there. It can be added again with the licence key.</p>
        </Dialog>
      )}
    </Card>
  )
}
