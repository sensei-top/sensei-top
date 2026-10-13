import { useTranslation } from 'react-i18next'
import { TextLink } from '../ui'

/** The line under a draft's header that says sharing draft data is on,
 *  with the way to Settings' section. Drawn only where the shell offers
 *  sharing; nothing when it is off. */
export function SharingNote({ on }: { on: boolean }) {
  const { t } = useTranslation()
  if (!on) return null
  return (
    <p className="text-caption text-ink2">
      {t('prompts.sharing.note.on')}{' '}
      <TextLink href="/settings#draft-data" className="inline-flex min-h-[44px] items-center">
        {t('prompts.sharing.note.settings')}
      </TextLink>
    </p>
  )
}
