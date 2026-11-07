import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { DeleteFailure } from './accountLogic'
import { Button, Dialog, MoreAbout } from '../ui'

/** A dialog of the account's, one question: Cancel first in the source (the
 *  dialog focuses it) and the primary button, the confirm second. While the
 *  call runs both are disabled and only the pressed one says it works. */
function QuestionDialog({
  open,
  title,
  confirm,
  working,
  busy,
  failure,
  onCancel,
  onConfirm,
  children,
}: {
  open: boolean
  title: string
  confirm: string
  working: string
  busy: boolean
  failure: string | null
  onCancel: () => void
  onConfirm: () => void
  children: ReactNode
}) {
  const { t } = useTranslation()
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      actions={
        <>
          <Button variant="primary" className="min-h-[44px]" disabled={busy} onClick={onCancel}>
            {t('account.dialog.cancel')}
          </Button>
          <Button className="min-h-[44px]" disabled={busy} onClick={onConfirm}>
            {busy ? working : confirm}
          </Button>
        </>
      }
    >
      <div className="space-y-2">
        {children}
        {failure && (
          <p role="alert" className="break-words text-caption text-loss">
            {failure}
          </p>
        )}
      </div>
    </Dialog>
  )
}

type DeleteProps = {
  open: boolean
  busy: boolean
  failure: DeleteFailure | null
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteHistoryDialog({ open, busy, failure, onCancel, onConfirm }: DeleteProps) {
  const { t } = useTranslation()
  return (
    <QuestionDialog
      open={open}
      title={t('account.deleteHistory.title')}
      confirm={t('account.deleteHistory.confirm')}
      working={t('account.dialog.working')}
      busy={busy}
      failure={failure && t(`account.deleteHistory.failed.${failure}`)}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <p>{t('account.deleteHistory.body1')}</p>
      <p>{t('account.deleteHistory.body2')}</p>
      <p>{t('account.deleteHistory.body3')}</p>
    </QuestionDialog>
  )
}

export function DeleteAccountDialog({ open, busy, failure, onCancel, onConfirm }: DeleteProps) {
  const { t } = useTranslation()
  return (
    <QuestionDialog
      open={open}
      title={t('account.deleteAccount.title')}
      confirm={t('account.deleteAccount.confirm')}
      working={t('account.dialog.working')}
      busy={busy}
      failure={failure && t('account.deleteAccount.failed')}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <p>{t('account.deleteAccount.body1')}</p>
      <p>{t('account.deleteAccount.body2')}</p>
      <p>{t('account.deleteAccount.body3')}</p>
      <p>{t('account.deleteAccount.body4')}</p>
    </QuestionDialog>
  )
}

export function ErrorsDialog({
  open,
  busy,
  failure,
  onCancel,
  onConfirm,
}: {
  open: boolean
  busy: boolean
  failure: string | null
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation()
  return (
    <QuestionDialog
      open={open}
      title={t('account.errorsDialog.title')}
      confirm={t('account.errorsDialog.confirm')}
      working={t('account.dialog.working')}
      busy={busy}
      failure={failure}
      onCancel={onCancel}
      onConfirm={onConfirm}
    >
      <p>{t('account.errorsDialog.withdraw')}</p>
      <MoreAbout>
        <p>{t('account.welcome.transfer.law')}</p>
        <p>{t('account.welcome.transfer.ip')}</p>
      </MoreAbout>
    </QuestionDialog>
  )
}
