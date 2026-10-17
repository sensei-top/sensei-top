import { Settings } from 'lucide-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * Where Arena keeps Detailed Logs, as three panels of our own drawing rather
 * than Arena's screens: its home screen with the Options gear at top right,
 * the Options menu with Account, and Account's list with Detailed Logs
 * (Plugin Support) ticked, then a caption to start Arena again. Each panel
 * reduces Arena to muted placeholder bars, so the drawing never invents a
 * label of Arena's it does not name; the one thing to press wears the accent,
 * with its step's number in an accent disc.
 *
 * Not one SVG per panel, as the plan's S3 has it: the frames and the accent
 * rings are HTML boxes with CSS borders, because a ring drawn in a fixed SVG
 * would not grow around a label that wraps in PT-BR or when the panels
 * stack. Only the gear, the bars and the checkboxes are SVG. The three labels
 * are HTML text inside those boxes, so they wrap in a longer language and
 * stay selectable. The whole drawing is one image whose
 * `aria-label` says the three steps and the restart in a sentence, and its
 * own text is hidden from a screen reader, which hears the sentence once.
 * `compact` is the Home banner's size: the same panels at about 60% of the
 * height, with fewer bars and its text in caption type. Below `sm` the panels
 * stack into one column.
 */
export function DetailedLogsGuide({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation()
  const label = `${compact ? 'text-caption' : 'text-body'} font-semibold text-ink`
  return (
    <div role="img" aria-label={t('welcome.guide.aria')}>
      <div aria-hidden className={compact ? 'space-y-2' : 'space-y-3'}>
        <div className={`grid sm:grid-cols-[1fr_1fr_1.4fr] ${compact ? 'gap-2' : 'gap-3'}`}>
          <Panel compact={compact}>
            <div className="flex items-start justify-between gap-3">
              <Bar className="mt-1 w-1/3" />
              {/* The gear is what the user has to find, so its number sits
                  beside the ring rather than on it. */}
              <div className="flex items-start gap-1">
                <div className="flex flex-col items-center gap-1">
                  <span className={`rounded-pill border-2 border-accent text-accent ${compact ? 'p-1' : 'p-1.5'}`}>
                    <Settings size={compact ? 16 : 20} strokeWidth={2.25} />
                  </span>
                  <span className={`text-center ${label}`}>{t('welcome.guide.options')}</span>
                </div>
                <Badge n={1} compact={compact} beside />
              </div>
            </div>
            <Bar className="w-2/3" />
            {!compact && <Bar className="w-1/2" />}
          </Panel>
          <Panel compact={compact}>
            <Bar className="w-1/2" />
            <Highlight n={2} compact={compact}>
              <span className={label}>{t('welcome.guide.account')}</span>
            </Highlight>
            <Bar className="w-2/3" />
            {!compact && <Bar className="w-1/2" />}
          </Panel>
          <Panel compact={compact}>
            <Bar className="w-2/3" />
            <CheckboxRow compact={compact}>
              <Bar className="w-2/3" />
            </CheckboxRow>
            <Highlight n={3} compact={compact}>
              <span className="flex items-start gap-2">
                <Checkbox ticked compact={compact} />
                <span className={label}>{t('welcome.guide.detailed')}</span>
              </span>
            </Highlight>
            {!compact && (
              <CheckboxRow compact={compact}>
                <Bar className="w-1/2" />
              </CheckboxRow>
            )}
          </Panel>
        </div>
        <p className={`${compact ? 'text-caption' : 'text-body'} text-ink2`}>{t('welcome.guide.restart')}</p>
      </div>
    </div>
  )
}

/** One small framed screen of the drawing. */
function Panel({ compact, children }: { compact: boolean; children: ReactNode }) {
  return (
    <div
      className={`flex min-w-0 flex-col rounded-block border border-edge bg-surface2 ${
        compact ? 'gap-1.5 px-3 py-2.5' : 'gap-3 p-4'
      }`}
    >
      {children}
    </div>
  )
}

/** A placeholder for something of Arena's the drawing does not name. */
function Bar({ className }: { className: string }) {
  return (
    <svg className={`block h-1.5 shrink-0 ${className}`}>
      <rect width="100%" height="100%" rx="3" className="fill-muted/40" />
    </svg>
  )
}

/** The one thing to press in a panel: ringed in the accent, its step's
 *  number at its corner. */
function Highlight({ n, compact, children }: { n: number; compact: boolean; children: ReactNode }) {
  return (
    <div className={`relative rounded-control border-2 border-accent ${compact ? 'px-2 py-1' : 'px-3 py-2'}`}>
      {children}
      <Badge n={n} compact={compact} />
    </div>
  )
}

/** A step's number, in the accent disc a step that is next wears: on the
 *  corner of its highlighted box, or `beside` it in the flow where the box is
 *  too small to carry it without covering what it rings. */
function Badge({ n, compact, beside = false }: { n: number; compact: boolean; beside?: boolean }) {
  const place = beside ? 'shrink-0' : compact ? 'absolute -right-2 -top-2' : 'absolute -right-2.5 -top-2.5'
  return (
    <span
      className={`flex items-center justify-center rounded-pill bg-accent font-display font-extrabold text-on-accent ${place} ${
        compact ? 'size-5 text-chip' : 'size-6 text-caption'
      }`}
    >
      {n}
    </span>
  )
}

/** An unticked row of the list, lined up with the highlighted one's box. */
function CheckboxRow({ compact, children }: { compact: boolean; children: ReactNode }) {
  return (
    <div className={`flex items-center gap-2 ${compact ? 'px-2.5' : 'px-3.5'}`}>
      <Checkbox compact={compact} />
      {children}
    </div>
  )
}

/** A checkbox, ticked in the accent or left empty in muted. */
function Checkbox({ ticked = false, compact }: { ticked?: boolean; compact: boolean }) {
  return (
    <svg viewBox="0 0 16 16" className={`shrink-0 ${ticked ? 'mt-0.5' : ''} ${compact ? 'size-3.5' : 'size-4'}`}>
      {ticked ? (
        <>
          <rect x="0.5" y="0.5" width="15" height="15" rx="3.5" className="fill-accent" />
          <path
            d="M4.25 8.25 6.75 10.75 11.75 5.5"
            fill="none"
            strokeWidth="2"
            // Classes, not strokeLinecap/strokeLinejoin attributes: web/scripts/i18nCheck.test.ts flags letter-bearing literals in any attribute not on NOT_TEXT.
            className="stroke-on-accent [stroke-linecap:round] [stroke-linejoin:round]"
          />
        </>
      ) : (
        <rect x="1" y="1" width="14" height="14" rx="3" fill="none" strokeWidth="1.5" className="stroke-muted/60" />
      )}
    </svg>
  )
}
