import { useState, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from '../../i18n'
import { useLocation } from 'react-router'
import type { Deleted, Saved, Sharing } from '../../bridge'
import { answerOf, pressFailure } from '../../lib/settings'
import { NeverSent } from '../sharing/PayloadView'
import { Button, Card, Dialog, Field, SectionLabel, TextLink } from '../ui'
import { PressButton, SavingSwitch } from './SaveButton'

/** How many drafts have been sent, as a sentence. */
function sentSentence(sent: number, t: TFunction): string {
  if (sent === 0) return t('settings.sharing.sentNone')
  return t('settings.sharing.sentCount', { count: sent })
}

/** What the server said it deleted, as a sentence. */
function deletedSentence(count: number, t: TFunction): string {
  if (count === 0) return t('settings.sharing.deletedNone')
  return t('settings.sharing.deletedCount', { count })
}

/** Settings' section "Draft data", one card: the switch that shares
 *  finished drafts, off until the viewer turns it on; what is sent and
 *  what never is; the way to what the last finished draft sends, or would;
 *  how many drafts were sent; this installation's id and the way to a new
 *  one, which asks first; and, under a rule, the deletion of every draft
 *  sent, which asks first and then says what the server answered. Drawn by
 *  a shell that offers sharing. `payloadHref` is where a
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
  const { t } = useTranslation()
  return (
    <Card title={t('settings.sharing.title')} subtitle={t('settings.sharing.subtitle')} className="max-w-3xl">
      <div className="space-y-5">
        <SavingSwitch
          label={t('settings.sharing.share')}
          description={
            sharing.on ? t('settings.sharing.shareOn') : t('settings.sharing.shareOff')
          }
          checked={sharing.on}
          onSave={setSharing}
        />
        <div className="space-y-2">
          <SectionLabel>{t('settings.sharing.whatIsSent')}</SectionLabel>
          <Sent />
        </div>
        <div className="space-y-2">
          <SectionLabel>{t('settings.sharing.whatIsNeverSent')}</SectionLabel>
          <NeverSent />
        </div>
        <div className="space-y-1">
          {sharing.lastDraft === null ? (
            <p className="text-body text-ink2">{t('settings.sharing.noDraftYet')}</p>
          ) : (
            payloadHref && (
              <p className="text-body">
                <PayloadLink href={payloadHref}>
                  {sharing.on ? t('settings.sharing.seeSent') : t('settings.sharing.seeWouldSend')}
                </PayloadLink>
              </p>
            )
          )}
          <p className="text-body text-ink2">{sentSentence(sharing.sent, t)}</p>
        </div>
        <Installation id={sharing.installation} newInstallation={newInstallation} />
        {deleteContributions && <DeleteAll deleteContributions={deleteContributions} />}
      </div>
    </Card>
  )
}

/** What is sent, a line each, as a short list. */
function Sent() {
  const { t } = useTranslation()
  const lines = [
    t('settings.sharing.sentList.event'),
    t('settings.sharing.sentList.picks'),
    t('settings.sharing.sentList.deck'),
    t('settings.sharing.sentList.opponent'),
    t('settings.sharing.sentList.rank'),
    t('settings.sharing.sentList.install'),
  ]
  return (
    <ul className="list-disc space-y-1 pl-5 text-body text-ink2 marker:text-muted">
      {lines.map((line) => (
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
  const { t } = useTranslation()
  const [asking, setAsking] = useState(false)
  const [making, setMaking] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const make = async () => {
    if (!newInstallation) return
    setMaking(true)
    setFailure(null)
    const sentence = pressFailure(await answerOf(newInstallation()), t('settings.sharing.notMade'))
    setMaking(false)
    setFailure(sentence)
  }

  return (
    <div className="space-y-2">
      <Field
        label={t('settings.sharing.installationLabel')}
        value={id}
        hint={t('settings.sharing.installationHint')}
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
            {t('settings.sharing.makeNew')}
          </Button>
          {failure && <p className="break-words text-caption text-loss">{failure}</p>}
          <Dialog
            open={asking}
            onClose={() => setAsking(false)}
            title={t('settings.sharing.makeNewTitle')}
            actions={
              <>
                <Button variant="primary" className="min-h-[44px]" onClick={() => setAsking(false)}>
                  {t('settings.sharing.keepId')}
                </Button>
                <Button
                  className="min-h-[44px]"
                  onClick={() => {
                    setAsking(false)
                    void make()
                  }}
                >
                  {t('settings.sharing.makeNewConfirm')}
                </Button>
              </>
            }
          >
            <p>{t('settings.sharing.makeNewBody')}</p>
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
  const { t } = useTranslation()
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<{ sentence: string; failed: boolean } | null>(null)

  const remove = async (): Promise<boolean> => {
    setAnswer(null)
    const deleted = await deleteContributions().catch((): Deleted => ({ ok: false, error: '' }))
    setAsking(false)
    if (!deleted.ok) {
      setAnswer({ sentence: deleted.error.trim() || t('settings.sharing.notDeleted'), failed: true })
      return false
    }
    setAnswer({ sentence: deletedSentence(deleted.count, t), failed: false })
    return true
  }

  return (
    <div className="space-y-1.5 border-t border-edge pt-5">
      <Button variant="quiet" className="min-h-[44px]" aria-haspopup="dialog" onClick={() => setAsking(true)}>
        {t('settings.sharing.deleteAll')}
      </Button>
      {answer && (
        <p className={`break-words ${answer.failed ? 'text-caption text-loss' : 'text-body text-ink2'}`}>
          {answer.sentence}
        </p>
      )}
      <Dialog
        open={asking}
        onClose={() => setAsking(false)}
        title={t('settings.sharing.deleteTitle')}
        actions={
          <>
            <Button variant="primary" className="min-h-[44px]" onClick={() => setAsking(false)}>
              {t('settings.sharing.keepThem')}
            </Button>
            <PressButton
              variant="secondary"
              label={t('settings.sharing.deleteThem')}
              workingLabel={t('settings.sharing.deleting')}
              doneLabel={null}
              onPress={remove}
            />
          </>
        }
      >
        <p>{t('settings.sharing.deleteBody')}</p>
      </Dialog>
    </div>
  )
}
