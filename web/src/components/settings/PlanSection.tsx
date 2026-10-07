import { useState } from 'react'
import type { Device, Offer, Plan, Saved } from '../../bridge'
import {
  activeSentence,
  answerOf,
  endedSentence,
  KEY_REFUSED,
  offerButton,
  PAGE_NOT_OPENED,
  paymentFailedSentence,
  pressFailure,
  pricesSentence,
  trialOfferSentence,
  trialSentence,
  trialThenSentence,
} from '../../lib/plan'
import { useNow } from '../../lib/time'
import { Callout, Card, Field, type ButtonVariant } from '../ui'
import { AllowanceMeter } from './AllowanceMeter'
import { DevicesCard } from './DevicesCard'
import { PressButton } from './SaveButton'

/** Settings' section "Plan": the plan the viewer has, or the offer of one,
 *  in one card, and under a running plan the computers it works on. The
 *  offer is the one place in the app a price is written, and each price is
 *  the shell's text, drawn as it comes. Drawn only by a shell that sells a
 *  plan: `not-offered` draws nothing, and with no shell the page never
 *  draws this section. With a function missing, what it would do has
 *  nothing to press. */
export function PlanSection({
  plan,
  devices,
  deviceLimit,
  activate,
  startTrial,
  managePlan,
  removeDevice,
}: {
  plan: Plan
  devices: Device[]
  deviceLimit: number
  activate?: (key: string) => Promise<Saved>
  startTrial?: () => Promise<Saved>
  managePlan?: () => Promise<Saved>
  removeDevice?: (id: string) => Promise<Saved>
}) {
  const now = useNow()

  switch (plan.state) {
    case 'not-offered':
      return null
    case 'none':
      return <OfferCard offer={plan.offer} startTrial={startTrial} activate={activate} />
    case 'ended': {
      const ended = endedSentence(plan.on, now)
      return (
        <>
          {ended && <p className="max-w-3xl text-body text-ink2">{ended}</p>}
          <OfferCard offer={plan.offer} startTrial={startTrial} activate={activate} />
        </>
      )
    }
    case 'trial': {
      const days = trialSentence(plan.ends, now)
      const then = trialThenSentence(plan.ends, plan.then, now)
      return (
        <>
          <Card title="Pro, on trial" className="max-w-3xl">
            <div className="space-y-5">
              {(days || then) && (
                <div className="space-y-1.5 text-body text-ink2">
                  {days && <p>{days}</p>}
                  {then && <p>{then}</p>}
                </div>
              )}
              <AllowanceMeter allowance={plan.allowance} onTrial now={now} />
              {managePlan && <ManageButton variant="secondary" managePlan={managePlan} withNote />}
            </div>
          </Card>
          <DevicesCard devices={devices} limit={deviceLimit} removeDevice={removeDevice} now={now} />
        </>
      )
    }
    case 'active': {
      const sentence = activeSentence(plan.every, plan.renews, plan.until, now)
      return (
        <>
          <Card title="Pro" className="max-w-3xl">
            <div className="space-y-5">
              {sentence && <p className="text-body text-ink2">{sentence}</p>}
              <AllowanceMeter allowance={plan.allowance} onTrial={false} now={now} />
              {managePlan && <ManageButton variant="secondary" managePlan={managePlan} withNote />}
            </div>
          </Card>
          <DevicesCard devices={devices} limit={deviceLimit} removeDevice={removeDevice} now={now} />
        </>
      )
    }
    case 'payment-failed': {
      const sentence = paymentFailedSentence(plan.until, now)
      return (
        <>
          <Card title="Pro" className="max-w-3xl">
            <div className="space-y-5">
              <Callout tone="warn" title="The last payment failed">
                <div className="space-y-3">
                  {sentence && <p>{sentence}</p>}
                  {managePlan && <ManageButton variant="primary" managePlan={managePlan} withNote={false} />}
                </div>
              </Callout>
              <AllowanceMeter allowance={plan.allowance} onTrial={false} now={now} />
            </div>
          </Card>
          <DevicesCard devices={devices} limit={deviceLimit} removeDevice={removeDevice} now={now} />
        </>
      )
    }
  }
}

/** "Manage the plan": the shell opens the page where the plan is changed
 *  or cancelled. While the shell answers the button says "Opening" and is
 *  disabled; a failure's sentence is under it. `withNote` adds the line that says
 *  where it goes. */
function ManageButton({
  variant,
  managePlan,
  withNote,
}: {
  variant: ButtonVariant
  managePlan: () => Promise<Saved>
  withNote: boolean
}) {
  const [failure, setFailure] = useState<string | null>(null)
  const open = async (): Promise<boolean> => {
    setFailure(null)
    const sentence = pressFailure(await answerOf(managePlan()), PAGE_NOT_OPENED)
    setFailure(sentence)
    return sentence === null
  }
  return (
    <div className="space-y-1.5">
      <PressButton
        variant={variant}
        label="Manage the plan"
        workingLabel="Opening"
        doneLabel={null}
        onPress={open}
      />
      {withNote && <p className="text-caption text-muted">Opens the page where the plan is changed or cancelled.</p>}
      {failure && <p className="break-words text-caption text-loss">{failure}</p>}
    </div>
  )
}

/** The offer to a viewer with no plan, in a card of tone `accent`: what
 *  the plan holds, its two prices as the shell wrote them, the button to
 *  the checkout and what the trial is, then, under a rule, the licence
 *  key's field for a key bought elsewhere. */
function OfferCard({
  offer,
  startTrial,
  activate,
}: {
  offer: Offer
  startTrial?: () => Promise<Saved>
  activate?: (key: string) => Promise<Saved>
}) {
  const [failure, setFailure] = useState<string | null>(null)
  const checkout = async (): Promise<boolean> => {
    if (!startTrial) return false
    setFailure(null)
    const sentence = pressFailure(await answerOf(startTrial()), PAGE_NOT_OPENED)
    setFailure(sentence)
    return sentence === null
  }
  const button = offerButton(offer.trialDays)

  return (
    <Card title="Pro" subtitle="Your reports, written for you." tone="accent" className="max-w-3xl">
      <div className="space-y-5">
        <ul className="list-disc space-y-1 pl-5 text-body text-ink2 marker:text-muted">
          <li>Every report written by Claude's Opus, with nothing to copy or paste.</li>
          <li>An allowance each month that covers a regular month of play.</li>
          <li>The coach reads the web for what changed in the format.</li>
          <li>Your matches kept in an encrypted copy, and the same on every computer you play on.</li>
        </ul>
        <p className="text-body text-ink">{pricesSentence(offer.byMonth, offer.byYear)}</p>
        {startTrial && (
          <div className="space-y-1.5">
            <PressButton variant="primary" label={button} workingLabel="Opening" doneLabel={null} onPress={checkout} />
            {offer.trialDays !== null && (
              <p className="text-caption text-muted">{trialOfferSentence(offer.trialDays)}</p>
            )}
            {failure && <p className="break-words text-caption text-loss">{failure}</p>}
          </div>
        )}
        {activate && (
          <div className="border-t border-edge pt-5">
            <LicenceKey activate={activate} />
          </div>
        )}
        <p className="text-caption text-muted">
          What is free stays free: every page, every report's prompt, and a key of your own.
        </p>
      </div>
    </Card>
  )
}

/** The licence key's field and "Activate". What is typed lives in this
 *  block's own state alone, leaves the page only through `activate`, and
 *  is cleared when that answers that it worked. The field is plain text,
 *  since the key is on a receipt and is read back against it; a refused
 *  key stays in the field for that reason, with the shell's sentence, or
 *  the plain one, under it. */
function LicenceKey({ activate }: { activate: (key: string) => Promise<Saved> }) {
  const [typed, setTyped] = useState('')
  const [error, setError] = useState<string | undefined>(undefined)

  const send = async (): Promise<boolean> => {
    const key = typed.trim()
    if (key === '') return false
    setError(undefined)
    const sentence = pressFailure(await answerOf(activate(key)), KEY_REFUSED)
    if (sentence === null) {
      setTyped('')
      return true
    }
    setError(sentence)
    return false
  }

  return (
    <div className="space-y-3">
      <p className="text-body text-ink">Already have a key?</p>
      <Field
        label="Licence key"
        type="text"
        autoComplete="off"
        value={typed}
        onChange={setTyped}
        placeholder="Paste the key from your receipt"
        error={error}
      />
      <PressButton
        variant="secondary"
        label="Activate"
        workingLabel="Activating"
        doneLabel={null}
        disabled={typed.trim() === ''}
        onPress={send}
      />
    </div>
  )
}
