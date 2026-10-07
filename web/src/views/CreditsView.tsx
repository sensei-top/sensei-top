import type { ReactNode } from 'react'
import { Card, TextLink } from '../components/ui'
import { credits } from '../credits'

/** One entry of a credits list: the name as its link, then its lines. */
function CreditEntry({ name, url, children }: { name: string; url: string; children: ReactNode }) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="text-body font-medium">
        <TextLink href={url}>{name}</TextLink>
      </div>
      <div className="mt-0.5 space-y-0.5 text-caption">{children}</div>
    </li>
  )
}

/** Wizards' notice, the data sources, the bundled fonts and glyphs, and this
 *  program's own notice. It sits under "About and credits" on `/settings`,
 *  whose heading stands for a title of its own; the footer's "Credits"
 *  links there. Every sentence comes from `credits.ts`. Every link leaves
 *  the app, so each opens in a new tab and the dashboard stays where it
 *  was. */
export function CreditsView() {
  const { wizards, dataSources, fonts, program } = credits
  return (
    <div className="max-w-3xl space-y-6">
      <Card title={wizards.heading}>
        <div className="space-y-3 text-body text-ink2">
          {wizards.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      </Card>

      <Card title={dataSources.heading}>
        <p className="text-body text-ink2">{dataSources.opening}</p>
        <ul className="mt-4 divide-y divide-line">
          {dataSources.entries.map((source) => (
            <CreditEntry key={source.name} name={source.name} url={source.url}>
              <p className="text-ink2">{source.taken}</p>
              <p className="text-muted">
                {source.termsUrl ? (
                  <TextLink href={source.termsUrl}>{source.terms}</TextLink>
                ) : (
                  source.terms
                )}
              </p>
            </CreditEntry>
          ))}
        </ul>
        <p className="mt-4 text-caption text-muted">{dataSources.closing}</p>
      </Card>

      <Card title={fonts.heading}>
        <p className="text-body text-ink2">{fonts.opening}</p>
        <ul className="mt-4 divide-y divide-line">
          {fonts.entries.map((font) => (
            <CreditEntry key={font.name} name={font.name} url={font.url}>
              <p className="text-ink2">{font.usedFor}</p>
              <p className="text-muted">{font.notice}</p>
            </CreditEntry>
          ))}
        </ul>
        <p className="mt-4 text-caption">
          <TextLink href={fonts.licence.url}>{fonts.licence.text}</TextLink>
        </p>
      </Card>

      <Card title={program.heading}>
        <div className="space-y-3 text-body text-ink2">
          {program.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      </Card>
    </div>
  )
}
