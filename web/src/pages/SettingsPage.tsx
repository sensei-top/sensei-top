import { useLLMStatus } from '../api'
import { useTranslation } from 'react-i18next'
import { useShell } from '../bridge'
import { SavingSwitch } from '../components/settings/SaveButton'
import { LanguageSection } from '../components/settings/LanguageSection'
import { Card, Segmented, Switch } from '../components/ui'
import { inGroup, type SettingsGroupId, type WritingStatusAnswer } from '../lib/settings'
import { useAiFeatures } from '../shell/aiFeatures'
import { useDensity } from '../shell/density'
import { useLiveAdvice } from '../shell/liveAdvice'
import { CreditsView } from '../views/CreditsView'
import { SettingsView } from '../views/SettingsView'

/** One of Settings' groups, `/settings/<group>`; which sections it holds is
 *  `lib/settings.ts`'s `groupOfHash`, their order `docs/frontend.md`,
 *  "Settings". The browser's own sections are drawn here and reach
 *  `SettingsView` as `lead` and `children`. `#credits` is where the footer's
 *  "Credits" lands; `scroll-mt-16` keeps the heading clear of the sticky
 *  strip under 48rem. */
export function SettingsPage({ group }: { group?: SettingsGroupId }) {
  const { t } = useTranslation()
  const shell = useShell()
  const status = useLLMStatus()
  const [density, setDensity] = useDensity()
  const [liveAdvice, setLiveAdvice] = useLiveAdvice()
  const [aiOn, setAiOn] = useAiFeatures()
  const densityOptions = [
    { value: 'comfortable' as const, label: t('settings.density.comfortable') },
    { value: 'compact' as const, label: t('settings.density.compact') },
  ]
  const writing: WritingStatusAnswer = status.data
    ? { configured: status.data.configured, model: status.data.model ?? null }
    : status.isError
      ? 'failed'
      : 'loading'
  const shows = (section: string) => inGroup(section, group)
  return (
    <div className="space-y-10">
      <SettingsView shell={shell} writing={writing} group={group} lead={
        <>
          {shows('language') && (
            <section id="language" aria-labelledby="language-heading" className="space-y-4">
              <h2 id="language-heading" className="font-display text-title text-ink">
                {t('settings.sections.language')}
              </h2>
              <LanguageSection />
            </section>
          )}
          {shows('appearance') && (
            <section aria-labelledby="appearance" className="space-y-4">
              <h2 id="appearance" className="font-display text-title text-ink">
                {t('settings.sections.appearance')}
              </h2>
              <Card className="max-w-3xl">
                <Segmented label={t('settings.density.label')} value={density} options={densityOptions} onChange={setDensity} />
                <p className="mt-3 text-caption text-muted">{t('settings.density.note')}</p>
              </Card>
            </section>
          )}
          {shows('live-settings') && (
            <section aria-labelledby="live-settings" className="space-y-4">
              <h2 id="live-settings" className="font-display text-title text-ink">
                {t('settings.sections.live')}
              </h2>
              <Card className="max-w-3xl">
                <Switch
                  label={t('settings.liveAdvice.label')}
                  description={aiOn ? t('settings.liveAdvice.description') : t('settings.liveAdvice.descriptionOff')}
                  checked={liveAdvice}
                  onChange={setLiveAdvice}
                />
              </Card>
            </section>
          )}
          {shows('ai-settings') && (
            <section aria-labelledby="ai-settings" className="space-y-4">
              <h2 id="ai-settings" className="font-display text-title text-ink">
                {t('settings.sections.ai')}
              </h2>
              <Card className="max-w-3xl">
                <SavingSwitch
                  label={t('settings.ai.label')}
                  description={t('settings.ai.description')}
                  checked={aiOn}
                  onSave={setAiOn}
                />
              </Card>
            </section>
          )}
        </>
      }>
        {shows('credits') && (
          <section id="credits" aria-labelledby="credits-heading" className="scroll-mt-16 space-y-4">
            <h2 id="credits-heading" className="font-display text-title text-ink">
              {t('settings.sections.credits')}
            </h2>
            <CreditsView />
          </section>
        )}
      </SettingsView>
    </div>
  )
}
