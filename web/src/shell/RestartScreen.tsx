import { useTranslation } from 'react-i18next'
import { BrandGlyph } from '../components/ui'

/** The restart screen: the top spinning on its point and hopping now and
 *  then (`index.css`, `.top-hop` and `.top-spin`; still under reduced
 *  motion), over one status line. The page stays mounted under it, hidden,
 *  so a button waiting on the restart keeps its state. */
export function RestartScreen() {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-5 text-center">
      <div className="top-hop text-accent">
        <div className="top-spin">
          <BrandGlyph size={56} />
        </div>
      </div>
      <p role="status" className="max-w-prose text-body text-ink2">
        {t('shell.restarting')}
      </p>
    </div>
  )
}
