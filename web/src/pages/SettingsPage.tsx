import { useLLMStatus } from '../api'
import { useTranslation } from 'react-i18next'
import { useShell } from '../bridge'
import { LanguageSection } from '../components/settings/LanguageSection'
import { Card, Segmented } from '../components/ui'
import type { WritingStatusAnswer } from '../components/settings/WritingSection'
import { useDensity } from '../shell/density'
import { CreditsView } from '../views/CreditsView'
import { SettingsView } from '../views/SettingsView'

/** `/settings`: the language first, then the shell's settings and what the
 *  API says of writing, then the density control, which is the browser's
 *  own, then what the credits show. With no shell that is the language,
 *  Writing as sentences, the density and the credits. `#credits` is where
 *  the footer's "Credits" lands; `scroll-mt-16` keeps the heading clear of
 *  the sticky strip under 48rem. */
export function SettingsPage() {
  const { t } = useTranslation()
  const shell = useShell()
  const status = useLLMStatus()
  const [density, setDensity] = useDensity()
  const densityOptions = [
    { value: 'comfortable' as const, label: t('settings.density.comfortable') },
    { value: 'compact' as const, label: t('settings.density.compact') },
  ]
  const writing: WritingStatusAnswer = status.data
    ? { configured: status.data.configured, model: status.data.model ?? null }
    : status.isError
      ? 'failed'
      : 'loading'
  return (
    <div className="space-y-10">
      <section id="language" aria-labelledby="language-heading" className="space-y-4">
        <h2 id="language-heading" className="font-display text-title text-ink">
          {t('settings.sections.language')}
        </h2>
        <LanguageSection />
      </section>
      <SettingsView shell={shell} writing={writing}>
        <section aria-labelledby="appearance" className="space-y-4">
          <h2 id="appearance" className="font-display text-title text-ink">
            {t('settings.sections.appearance')}
          </h2>
          <Card className="max-w-3xl">
            <Segmented label={t('settings.density.label')} value={density} options={densityOptions} onChange={setDensity} />
            <p className="mt-3 text-caption text-muted">{t('settings.density.note')}</p>
          </Card>
        </section>

        <section id="credits" aria-labelledby="credits-heading" className="scroll-mt-16 space-y-4">
          <h2 id="credits-heading" className="font-display text-title text-ink">
            {t('settings.sections.credits')}
          </h2>
          <CreditsView />
        </section>
      </SettingsView>
    </div>
  )
}
