import { useTranslation } from 'react-i18next'
import { useLanguage } from '../../i18n'
import { Card, Segmented } from '../ui'

/** The dashboard's language: "System" or one of the two. It reads and writes
 *  the page's own state (`useLanguage`), so it works with no shell. */
export function LanguageSection() {
  const { t } = useTranslation()
  const { choice, language, setLanguage } = useLanguage()
  const options = [
    { value: 'system' as const, label: t('settings.language.system') },
    { value: 'en' as const, label: t('common.languages.en') },
    { value: 'pt-BR' as const, label: t('common.languages.pt-BR') },
  ]
  return (
    <Card className="max-w-3xl">
      <div className="space-y-2">
        <Segmented label={t('settings.language.label')} value={choice} options={options} onChange={setLanguage} />
        {choice === 'system' && (
          <p className="text-caption text-muted">
            {t('settings.language.following', { language: t(`common.languages.${language}`) })}
          </p>
        )}
        <p className="text-caption text-muted">{t('settings.language.description')}</p>
      </div>
    </Card>
  )
}
