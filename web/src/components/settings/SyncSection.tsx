import { useState, type MouseEvent, type ReactNode } from 'react'
import { useLocation } from 'react-router'
import type { Saved, Sync, SyncSetUp } from '../../bridge'
import { answerOf, pressFailure } from '../../lib/plan'
import {
  CLOUD_DELETED,
  lastSyncedSentence,
  NOT_DELETED,
  passphraseCheck,
  pauseCallout,
  setUpAnswer,
  setUpFailure,
  storagePart,
  storageSentence,
  SYNC_FAILED,
  SYNC_WARNING,
  UNLOCK_FAILED,
} from '../../lib/sync'
import { useNow } from '../../lib/time'
import { Button, Callout, Card, Dialog, Field, Meter, SectionLabel, TextBlock, TextLink } from '../ui'
import { PressButton, SavingSwitch } from './SaveButton'

type RunningSync = Extract<Sync, { state: 'on' | 'paused' }>

/** Settings' section "Cloud sync", one card in every state: with no plan a
 *  sentence and a link to the plan; with a plan and no sync, what it does
 *  and the button that opens its setup in the card; on or paused, the
 *  switch, the last sync, the storage and the way to delete the copy,
 *  under a callout when paused; locked, the field that opens the copy
 *  here. The passphrase, its second typing and the recovery code live in
 *  this component's state alone: the two fields are emptied when the first
 *  step ends, and the code is dropped when the second does, after which
 *  the card draws the state the shell says. Drawn by a shell that sells a
 *  plan; with a function missing, what it would do has nothing to press. */
export function SyncSection({
  sync,
  setUpSync,
  unlockSync,
  setSync,
  syncNow,
  deleteCloudData,
}: {
  sync: Sync
  setUpSync?: (passphrase: string) => Promise<SyncSetUp>
  unlockSync?: (passphraseOrCode: string) => Promise<Saved>
  setSync?: (on: boolean) => Promise<Saved>
  syncNow?: () => Promise<Saved>
  deleteCloudData?: () => Promise<Saved>
}) {
  const [settingUp, setSettingUp] = useState(false)
  const [passphrase, setPassphrase] = useState('')
  const [again, setAgain] = useState('')
  const [setUpError, setSetUpError] = useState<string | null>(null)
  const [inFlight, setInFlight] = useState(false)
  const [recovery, setRecovery] = useState<string | null>(null)
  const [unlockTyped, setUnlockTyped] = useState('')
  const [unlockError, setUnlockError] = useState<string | undefined>(undefined)
  const [deleted, setDeleted] = useState(false)

  const endStepOne = () => {
    setPassphrase('')
    setAgain('')
    setSetUpError(null)
    setSettingUp(false)
  }

  const setUp = async (): Promise<boolean> => {
    const check = passphraseCheck(passphrase, again)
    if (!setUpSync || !check.ready) return false
    setSetUpError(null)
    setInFlight(true)
    const answer = await setUpAnswer(setUpSync(passphrase))
    setInFlight(false)
    const sentence = setUpFailure(answer)
    if (sentence !== null || !answer.ok) {
      setSetUpError(sentence)
      return false
    }
    endStepOne()
    setRecovery(answer.recovery)
    return true
  }

  const unlock = async (): Promise<boolean> => {
    if (!unlockSync || unlockTyped === '') return false
    setUnlockError(undefined)
    const sentence = pressFailure(await answerOf(unlockSync(unlockTyped)), UNLOCK_FAILED)
    // Emptied whatever the answer: the field is a password's, and what was
    // typed is typed again rather than kept.
    setUnlockTyped('')
    if (sentence !== null) setUnlockError(sentence)
    return sentence === null
  }

  const deletedLine = deleted && <p className="text-body text-ink2">{CLOUD_DELETED}</p>

  if (recovery !== null) {
    return (
      <SyncCard>
        <StepTwo recovery={recovery} onKept={() => setRecovery(null)} />
      </SyncCard>
    )
  }

  if (settingUp) {
    const check = passphraseCheck(passphrase, again)
    return (
      <SyncCard>
        <div className="space-y-5">
          <SectionLabel>Step 1 of 2: a passphrase</SectionLabel>
          <Field
            label="Passphrase"
            type="password"
            autoComplete="new-password"
            value={passphrase}
            onChange={setPassphrase}
            hint="12 characters or more. It never leaves this computer."
            error={check.short ?? undefined}
            disabled={inFlight}
          />
          <Field
            label="The passphrase again"
            type="password"
            autoComplete="new-password"
            value={again}
            onChange={setAgain}
            error={check.differ ?? undefined}
            disabled={inFlight}
          />
          <Callout tone="warn">
            <p>{SYNC_WARNING}</p>
          </Callout>
          <div className="space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <PressButton
                variant="primary"
                label="Continue"
                workingLabel="Setting up"
                doneLabel={null}
                disabled={!check.ready}
                onPress={setUp}
              />
              <Button variant="quiet" className="min-h-[44px]" disabled={inFlight} onClick={endStepOne}>
                Cancel
              </Button>
            </div>
            {setUpError && <p className="break-words text-caption text-loss">{setUpError}</p>}
          </div>
        </div>
      </SyncCard>
    )
  }

  switch (sync.state) {
    case 'no-plan':
      return (
        <SyncCard>
          <div className="space-y-3">
            <p className="text-body text-ink2">
              An encrypted copy of your matches, and the same matches on every computer you play on. It comes with
              Pro.
            </p>
            <SectionLink id="plan">See the plan</SectionLink>
          </div>
        </SyncCard>
      )
    case 'off':
      return (
        <SyncCard>
          <div className="space-y-5">
            {deletedLine}
            <div className="space-y-1.5 text-body text-ink2">
              <p>
                Keeps an encrypted copy of your matches, and brings the same matches to every computer you play on.
              </p>
              <p>
                The copy is locked on this computer with a passphrase you choose. Nobody else can read it, and that
                includes us.
              </p>
            </div>
            {setUpSync && (
              <Button
                variant="primary"
                className="min-h-[44px]"
                onClick={() => {
                  setDeleted(false)
                  setSetUpError(null)
                  setSettingUp(true)
                }}
              >
                Set up cloud sync
              </Button>
            )}
          </div>
        </SyncCard>
      )
    case 'locked':
      return (
        <SyncCard>
          <div className="space-y-5">
            <p className="text-body text-ink2">A cloud copy exists. Type its passphrase to bring it to this computer.</p>
            <Field
              label="Passphrase or recovery code"
              type="password"
              autoComplete="off"
              value={unlockTyped}
              onChange={unlockSync && setUnlockTyped}
              error={unlockError}
            />
            {unlockSync && (
              <PressButton
                variant="primary"
                label="Unlock"
                workingLabel="Unlocking"
                doneLabel={null}
                disabled={unlockTyped === ''}
                onPress={unlock}
              />
            )}
          </div>
        </SyncCard>
      )
    case 'on':
    case 'paused':
      return (
        <SyncCard>
          <Running
            sync={sync}
            setSync={setSync}
            syncNow={syncNow}
            deleteCloudData={deleteCloudData}
            onDeleted={() => setDeleted(true)}
          />
        </SyncCard>
      )
  }
}

/** The card every state is drawn in. */
function SyncCard({ children }: { children: ReactNode }) {
  return (
    <Card title="Cloud sync" className="max-w-3xl">
      {children}
    </Card>
  )
}

/** A link to a section of this page, by its id: the page's own address with
 *  the section as its hash, so a new tab opens the same page, and a plain
 *  click goes to the section. Drawn by the "no plan" card, to the plan. */
function SectionLink({ id, children }: { id: string; children: ReactNode }) {
  const { pathname, search } = useLocation()
  return (
    <TextLink
      href={`${pathname}${search}#${id}`}
      className="inline-flex min-h-[44px] items-center"
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        // `TextLink` renders the router's `Link`, which leaves a click whose
        // default is prevented to this handler.
        event.preventDefault()
        document.getElementById(id)?.scrollIntoView({ block: 'start' })
      }}
    >
      {children}
    </TextLink>
  )
}

/** The setup's second step: the recovery code, shown once, in a block it
 *  can be read and written down from, the button that copies it, the
 *  warning a second time, and the button that ends the setup. Drawn while
 *  the card holds the code. */
function StepTwo({ recovery, onKept }: { recovery: string; onKept: () => void }) {
  const copy = async (): Promise<boolean> => {
    if (!navigator.clipboard) return false
    return navigator.clipboard.writeText(recovery).then(
      () => true,
      () => false,
    )
  }
  return (
    <div className="space-y-5">
      <SectionLabel>Step 2 of 2: the recovery code</SectionLabel>
      <p className="text-body text-ink2">
        This code opens the copy if the passphrase is lost. It is shown once. Write it down or print it, and keep it
        away from this computer.
      </p>
      <TextBlock>{recovery}</TextBlock>
      <PressButton
        variant="secondary"
        label="Copy the code"
        workingLabel="Copy the code"
        doneLabel="Copied"
        onPress={copy}
      />
      <Callout tone="warn">
        <p>{SYNC_WARNING}</p>
      </Callout>
      <Button variant="primary" className="min-h-[44px]" onClick={onKept}>
        I have kept the code
      </Button>
    </div>
  )
}

/** Sync on or paused: under a callout when paused, the switch for this
 *  computer, the last sync, the storage as a meter with its words, "Sync
 *  now" while the switch is on and a sync could run, which is not while
 *  paused by a full quota or a lapsed plan, the link to the computers on
 *  the plan and, under a rule, the deletion of the cloud copy, which asks
 *  first in a dialog whose safe button is the primary one. */
function Running({
  sync,
  setSync,
  syncNow,
  deleteCloudData,
  onDeleted,
}: {
  sync: RunningSync
  setSync?: (on: boolean) => Promise<Saved>
  syncNow?: () => Promise<Saved>
  deleteCloudData?: () => Promise<Saved>
  onDeleted: () => void
}) {
  const now = useNow()
  const [syncFailure, setSyncFailure] = useState<string | null>(null)
  const [asking, setAsking] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteFailure, setDeleteFailure] = useState<string | null>(null)

  const pause = sync.state === 'paused' ? pauseCallout(sync.why, sync.keptUntil, now) : null
  const last = lastSyncedSentence(sync.last, now)
  const part = storagePart(sync.bytes, sync.quota)
  // A full quota or a lapsed plan leaves nothing a sync could do.
  const canSync = sync.enabled && !(sync.state === 'paused' && (sync.why === 'quota' || sync.why === 'plan'))

  const pressSync = async (): Promise<boolean> => {
    if (!syncNow) return false
    setSyncFailure(null)
    const sentence = pressFailure(await answerOf(syncNow()), SYNC_FAILED)
    setSyncFailure(sentence)
    return sentence === null
  }

  const remove = async () => {
    if (!deleteCloudData) return
    setDeleting(true)
    setDeleteFailure(null)
    const sentence = pressFailure(await answerOf(deleteCloudData()), NOT_DELETED)
    setDeleting(false)
    if (sentence !== null) setDeleteFailure(sentence)
    else onDeleted()
  }

  return (
    <div className="space-y-5">
      {pause && (
        <Callout tone={pause.tone} title={pause.title}>
          <p>{pause.sentence}</p>
        </Callout>
      )}
      <SavingSwitch
        label="Sync this computer"
        description="Off, nothing is sent or fetched. The copy stays as it is."
        checked={sync.enabled}
        onSave={setSync}
      />
      {last && <p className="text-body text-ink2">{last}</p>}
      {part !== null && (
        <div className="space-y-2">
          <SectionLabel>Storage</SectionLabel>
          <div className="flex items-center gap-3">
            <div
              role="meter"
              aria-label="Storage used"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(part * 100)}
              className="min-w-0 flex-1"
            >
              <Meter fraction={part} color="muted" />
            </div>
            <span className="shrink-0 text-caption text-ink2 tabular-nums">
              {storageSentence(sync.bytes, sync.quota)}
            </span>
          </div>
        </div>
      )}
      {syncNow && canSync && (
        <div className="space-y-1.5">
          <PressButton
            variant="secondary"
            label="Sync now"
            workingLabel="Syncing"
            doneLabel="Synced"
            onPress={pressSync}
          />
          {syncFailure && <p className="break-words text-caption text-loss">{syncFailure}</p>}
        </div>
      )}
      <p className="text-body">
        <SectionLink id="plan">The computers on your plan</SectionLink>
      </p>
      {deleteCloudData && (
        <div className="space-y-1.5 border-t border-edge pt-5">
          <Button
            variant="quiet"
            className="min-h-[44px]"
            disabled={deleting}
            aria-haspopup="dialog"
            onClick={() => setAsking(true)}
          >
            Delete my cloud data
          </Button>
          {deleteFailure && <p className="break-words text-caption text-loss">{deleteFailure}</p>}
          <Dialog
            open={asking}
            onClose={() => setAsking(false)}
            title="Delete the cloud copy?"
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
                  Delete the copy
                </Button>
              </>
            }
          >
            <p>
              The copy on the server is deleted and sync is turned off. Your matches on this computer stay as they are.
            </p>
          </Dialog>
        </div>
      )}
    </div>
  )
}
