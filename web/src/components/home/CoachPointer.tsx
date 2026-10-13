import { useTranslation } from 'react-i18next'
import { Button, Card } from '../ui'

/** The coach on Home is a pointer: what it is, and the way there. Home
 *  never asks the coach's own routes for anything. */
export function CoachPointer() {
  const { t } = useTranslation()
  return (
    <Card title={t('home.coach.title')} className="flex flex-col">
      <p className="text-body text-ink2">{t('home.coach.body')}</p>
      <div className="mt-4">
        <Button href="/coach">{t('home.coach.open')}</Button>
      </div>
    </Card>
  )
}
