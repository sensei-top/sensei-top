import { useTranslation } from 'react-i18next'
import { Button, EmptyState } from '../components/ui'

/** Any address that is no place. The shell's `h1` already reads "No such
 *  page", so the empty state carries no title of its own. */
export function NotFoundPage() {
  const { t } = useTranslation()
  return (
    <EmptyState
      message={t('home.notFound.message')}
      action={
        <Button variant="primary" href="/">
          {t('home.notFound.goHome')}
        </Button>
      }
    />
  )
}
