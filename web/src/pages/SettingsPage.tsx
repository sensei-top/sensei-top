import { useLLMStatus } from '../api'
import { useShell } from '../bridge'
import { Card, Segmented } from '../components/ui'
import type { WritingStatusAnswer } from '../components/settings/WritingSection'
import { useDensity } from '../shell/density'
import { CreditsView } from '../views/CreditsView'
import { SettingsView } from '../views/SettingsView'

const DENSITY_OPTIONS = [
  { value: 'comfortable' as const, label: 'Comfortable' },
  { value: 'compact' as const, label: 'Compact' },
]

/** `/settings`: the shell's settings and what the API says of writing,
 *  then the density control, which is the browser's own, then what the
 *  credits show. With no shell that is Writing as sentences, the density
 *  and the credits. `#credits` is where the footer's "Credits" lands;
 *  `scroll-mt-16` keeps the heading clear of the sticky strip under 48rem. */
export function SettingsPage() {
  const shell = useShell()
  const status = useLLMStatus()
  const [density, setDensity] = useDensity()
  const writing: WritingStatusAnswer = status.data
    ? { configured: status.data.configured, model: status.data.model ?? null }
    : status.isError
      ? 'failed'
      : 'loading'
  return (
    <SettingsView shell={shell} writing={writing}>
      <section aria-labelledby="appearance" className="space-y-4">
        <h2 id="appearance" className="font-display text-title text-ink">
          Appearance
        </h2>
        <Card className="max-w-3xl">
          <Segmented label="Density" value={density} options={DENSITY_OPTIONS} onChange={setDensity} />
          <p className="mt-3 text-caption text-muted">
            Compact fits more on the screen. A narrow window is always compact.
          </p>
        </Card>
      </section>

      <section id="credits" aria-labelledby="credits-heading" className="scroll-mt-16 space-y-4">
        <h2 id="credits-heading" className="font-display text-title text-ink">
          About and credits
        </h2>
        <CreditsView />
      </section>
    </SettingsView>
  )
}
