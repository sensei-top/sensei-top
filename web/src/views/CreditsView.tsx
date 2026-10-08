import { useId, useState, type ReactNode } from 'react'
import { Button, Card, TextBlock, TextLink } from '../components/ui'
import { credits, sourceUrl } from '../credits'

/** One entry of a credits list: the name as its link (or as text, with no
 *  `url`), then its lines. */
function CreditEntry({ name, url, children }: { name: string; url: string | null; children: ReactNode }) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="text-body font-medium">{url === null ? name : <TextLink href={url}>{name}</TextLink>}</div>
      <div className="mt-0.5 space-y-0.5 text-caption">{children}</div>
    </li>
  )
}

type NoticesState = { kind: 'idle' } | { kind: 'loading' } | { kind: 'failed' } | { kind: 'ok'; text: string }

/** The dashboard's third-party notices, `third-party-notices.txt` at the
 *  root of web_dist, which the build writes (web/scripts/thirdPartyNotices.ts).
 *  Read only as text: the Vite dev server answers a file it does not have
 *  with index.html and a 200, which is a failure here, not notices. */
async function fetchNotices(path: string): Promise<string> {
  const response = await fetch(new URL(path, window.location.origin))
  const type = response.headers.get('content-type') ?? ''
  if (!response.ok || !type.startsWith('text/plain')) throw new Error(`${response.status} ${type}`)
  return response.text()
}

/** Shown in place rather than linked, since a link would replace the
 *  dashboard in the desktop app's window, which has no back button. Closed
 *  at first; the first opening fetches the file, and an opening after a
 *  failure tries again. A `TextBlock`, so the texts' own line breaks
 *  stay, a long line wraps rather than scrolling sideways, and the box
 *  scrolls inside itself past its height. */
function NoticesDisclosure() {
  const { notices } = credits.software
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<NoticesState>({ kind: 'idle' })
  const regionId = useId()

  const toggle = () => {
    const opening = !open
    setOpen(opening)
    if (opening && (state.kind === 'idle' || state.kind === 'failed')) {
      setState({ kind: 'loading' })
      fetchNotices(notices.path).then(
        (text) => setState({ kind: 'ok', text }),
        () => setState({ kind: 'failed' }),
      )
    }
  }

  return (
    <div className="pt-2">
      <Button variant="secondary" size="sm" onClick={toggle} aria-expanded={open} aria-controls={regionId}>
        {open ? notices.hide : notices.show}
      </Button>
      {open && (
        <div id={regionId} className="mt-3">
          {state.kind === 'ok' ? (
            <TextBlock scroll>{state.text}</TextBlock>
          ) : (
            <p className="text-ink2" role="status">
              {state.kind === 'failed' ? notices.failed : notices.loading}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/** Wizards' notice, the data sources, the bundled fonts and glyphs, the
 *  software it is built on (with the dashboard's own notices), and this
 *  program's own notice. It sits under "About and credits" on `/settings`,
 *  whose heading stands for a title of its own; the footer's "Credits"
 *  links there. Every sentence comes from `credits.ts`. Every link leaves
 *  the app, so each opens in a new tab and the dashboard stays where it
 *  was. */
export function CreditsView() {
  const { wizards, dataSources, fonts, software, program } = credits
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

      <Card title={software.heading}>
        <p className="text-body text-ink2">{software.opening}</p>
        <ul className="mt-4 divide-y divide-line">
          {software.entries.map((work) => (
            <CreditEntry key={work.name} name={work.name} url={work.url}>
              <p className="text-ink2">{work.usedFor}</p>
              <p className="text-muted">{work.notice}</p>
              {'showsNotices' in work && work.showsNotices && <NoticesDisclosure />}
            </CreditEntry>
          ))}
        </ul>
      </Card>

      <Card title={program.heading}>
        <div className="space-y-3 text-body text-ink2">
          {program.paragraphs.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
          <p className="text-caption">
            <TextLink href={program.licence.url}>{program.licence.text}</TextLink>
          </p>
          {sourceUrl !== null && (
            <p>
              <TextLink href={sourceUrl}>{program.sourceLinkText}</TextLink>
            </p>
          )}
        </div>
      </Card>
    </div>
  )
}
