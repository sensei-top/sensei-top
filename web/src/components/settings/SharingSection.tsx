import { useState, type MouseEvent } from 'react'
import { useLocation } from 'react-router'
import type { Deleted, Saved, Sharing } from '../../bridge'
import { answerOf, pressFailure } from '../../lib/plan'
import { NeverSent } from '../sharing/PayloadView'
import { Button, Card, Dialog, Field, SectionLabel, TextLink } from '../ui'
import { PressButton, SavingSwitch } from './SaveButton'

const SENT = [
  'The event, the set, and the hour the draft started and ended.',
  'Every pack you saw and the card you took from it.',
  "The deck you built, and each game's result, who played first and how many turns it took.",
  "The opponent's colours, when the app read them.",
  "Your Limited rank's tier, when the log has it.",
  "A random id for this installation, the app's version and the operating system.",
]

const NOT_DELETED = 'The server did not answer. Nothing was deleted. Try again.'
const NOT_MADE = 'No new id was made. Try again.'

/** How many drafts have been sent, as a sentence. */
function sentSentence(sent: number): string {
  if (sent === 0) return 'No draft has been sent.'
  if (sent === 1) return '1 draft has been sent.'
  return `${sent} drafts have been sent.`
}

/** What the server said it deleted, as a sentence. */
function deletedSentence(count: number): string {
  if (count === 0) return 'The server held no draft of yours.'
  if (count === 1) return 'The server deleted 1 draft.'
  return `The server deleted ${count} drafts.`
}

/** Settings' section "Draft data", one card: the switch that shares
 *  finished drafts, off until the viewer turns it on; what is sent and
 *  what never is; the way to what the last finished draft sends, or would;
 *  how many drafts were sent; this installation's id and the way to a new
 *  one, which asks first; and, under a rule, the deletion of every draft
 *  sent, which asks first and then says what the server answered. Drawn by
 *  a shell that offers sharing, whatever the plan. `payloadHref` is where a
 *  draft's payload is shown; with none, nothing links to it. With a
 *  function missing, what it would do has nothing to press. */
export function SharingSection({
  sharing,
  payloadHref,
  setSharing,
  newInstallation,
  deleteContributions,
}: {
  sharing: Sharing
  payloadHref?: string
  setSharing?: (on: boolean) => Promise<Saved>
  newInstallation?: () => Promise<Saved>
  deleteContributions?: () => Promise<Deleted>
}) {
  return (
    <Card
      title="Sharing your drafts"
      subtitle="Drafts shared by players become card ratings that anyone can download, for the queues nobody else measures."
      className="max-w-3xl"
    >
      <div className="space-y-5">
        <SavingSwitch
          label="Share my finished drafts"
          description={
            sharing.on ? 'On. Each draft is sent once its games are over, never during a game.' : 'Off. Nothing is sent.'
          }
          checked={sharing.on}
          onSave={setSharing}
        />
        <div className="space-y-2">
          <SectionLabel>What is sent</SectionLabel>
          <Sent />
        </div>
        <div className="space-y-2">
          <SectionLabel>What is never sent</SectionLabel>
          <NeverSent />
        </div>
        <div className="space-y-1">
          {sharing.lastDraft === null ? (
            <p className="text-body text-ink2">Once you finish a draft, what it would send is shown here.</p>
          ) : (
            payloadHref && (
              <p className="text-body">
                <PayloadLink href={payloadHref}>
                  {sharing.on ? 'See what your last draft sent' : 'See what your last draft would send'}
                </PayloadLink>
              </p>
            )
          )}
          <p className="text-body text-ink2">{sentSentence(sharing.sent)}</p>
        </div>
        <Installation id={sharing.installation} newInstallation={newInstallation} />
        {deleteContributions && <DeleteAll deleteContributions={deleteContributions} />}
      </div>
    </Card>
  )
}

/** What is sent, a line each, as a short list. */
function Sent() {
  return (
    <ul className="list-disc space-y-1 pl-5 text-body text-ink2 marker:text-muted">
      {SENT.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  )
}

/** The link to a draft's payload. An `href` that is a bare `#id` is a
 *  place on this page: the page's own address with that hash, and a plain
 *  click scrolls to it, since the router moves the address and nothing
 *  else. Any other `href` is a `TextLink`'s. */
function PayloadLink({ href, children }: { href: string; children: string }) {
  const { pathname, search } = useLocation()
  if (!href.startsWith('#')) {
    return (
      <TextLink href={href} className="inline-flex min-h-[44px] items-center">
        {children}
      </TextLink>
    )
  }
  return (
    <TextLink
      href={`${pathname}${search}${href}`}
      className="inline-flex min-h-[44px] items-center"
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        // `TextLink` renders the router's `Link`, which leaves a click whose
        // default is prevented to this handler.
        event.preventDefault()
        document.getElementById(href.slice(1))?.scrollIntoView({ block: 'start' })
      }}
    >
      {children}
    </TextLink>
  )
}

/** This installation's id, read-only, and "Make a new one", which asks
 *  first in a dialog whose safe button is the primary one and says what a
 *  new id leaves behind. A failure's sentence is under the button. */
function Installation({ id, newInstallation }: { id: string; newInstallation?: () => Promise<Saved> }) {
  const [asking, setAsking] = useState(false)
  const [making, setMaking] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const make = async () => {
    if (!newInstallation) return
    setMaking(true)
    setFailure(null)
    const sentence = pressFailure(await answerOf(newInstallation()), NOT_MADE)
    setMaking(false)
    setFailure(sentence)
  }

  return (
    <div className="space-y-2">
      <Field
        label="This installation's id"
        value={id}
        hint="A random id, made on this computer. It is how your drafts are told from another player's, and how they are found when you delete them."
      />
      {newInstallation && (
        <div className="space-y-1.5">
          <Button
            variant="quiet"
            className="min-h-[44px]"
            disabled={making}
            aria-haspopup="dialog"
            onClick={() => setAsking(true)}
          >
            Make a new one
          </Button>
          {failure && <p className="break-words text-caption text-loss">{failure}</p>}
          <Dialog
            open={asking}
            onClose={() => setAsking(false)}
            title="Make a new id?"
            actions={
              <>
                <Button variant="primary" className="min-h-[44px]" onClick={() => setAsking(false)}>
                  Keep this id
                </Button>
                <Button
                  className="min-h-[44px]"
                  onClick={() => {
                    setAsking(false)
                    void make()
                  }}
                >
                  Make a new id
                </Button>
              </>
            }
          >
            <p>
              The drafts already sent stay where they are, under the old id. With a new id they can no longer be found
              from this computer, so they can no longer be deleted from here. To delete them, do it before making a new
              id.
            </p>
          </Dialog>
        </div>
      )}
    </div>
  )
}

/** "Delete everything I sent", under a rule: it asks first, in a dialog
 *  whose safe button is the primary one and whose other says "Deleting"
 *  while the deletion is in flight; the dialog closes on the answer, and
 *  what the server said, or why nothing was deleted, is the line under
 *  the button. */
function DeleteAll({ deleteContributions }: { deleteContributions: () => Promise<Deleted> }) {
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<{ sentence: string; failed: boolean } | null>(null)

  const remove = async (): Promise<boolean> => {
    setAnswer(null)
    const deleted = await deleteContributions().catch((): Deleted => ({ ok: false, error: '' }))
    setAsking(false)
    if (!deleted.ok) {
      setAnswer({ sentence: deleted.error.trim() || NOT_DELETED, failed: true })
      return false
    }
    setAnswer({ sentence: deletedSentence(deleted.count), failed: false })
    return true
  }

  return (
    <div className="space-y-1.5 border-t border-edge pt-5">
      <Button variant="quiet" className="min-h-[44px]" aria-haspopup="dialog" onClick={() => setAsking(true)}>
        Delete everything I sent
      </Button>
      {answer && (
        <p className={`break-words ${answer.failed ? 'text-caption text-loss' : 'text-body text-ink2'}`}>
          {answer.sentence}
        </p>
      )}
      <Dialog
        open={asking}
        onClose={() => setAsking(false)}
        title="Delete every draft you sent?"
        actions={
          <>
            <Button variant="primary" className="min-h-[44px]" onClick={() => setAsking(false)}>
              Keep them
            </Button>
            <PressButton
              variant="secondary"
              label="Delete them"
              workingLabel="Deleting"
              doneLabel={null}
              onPress={remove}
            />
          </>
        }
      >
        <p>
          Every draft sent under this installation's id is deleted from the server. Ratings already published from them
          are not recomputed until the next night. Your drafts on this computer stay as they are.
        </p>
      </Dialog>
    </div>
  )
}
