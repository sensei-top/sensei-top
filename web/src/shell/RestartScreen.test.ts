import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import '../i18n'
import { RestartScreen } from './RestartScreen'
import { mainNotice, useRestartScreen } from './restarting'

function Probe({ restarting }: { restarting: boolean }) {
  return createElement('i', null, String(useRestartScreen(restarting)))
}

const drawProbe = (restarting: boolean) =>
  renderToStaticMarkup(createElement(QueryClientProvider, { client: new QueryClient() }, createElement(Probe, { restarting })))

describe('the restart screen', () => {
  it('takes the place of the tracker-down notice while the shell restarts the server', () => {
    expect(mainNotice(true, true)).toBe('restarting')
    expect(mainNotice(true, false)).toBe('restarting')
  })

  it('leaves the notice to a failed heartbeat at any other time', () => {
    expect(mainNotice(false, true)).toBe('trackerDown')
    expect(mainNotice(false, false)).toBeNull()
  })

  it('shows while the shell says it is restarting, and not otherwise', () => {
    expect(drawProbe(true)).toBe('<i>true</i>')
    expect(drawProbe(false)).toBe('<i>false</i>')
  })

  it('says it is applying the changes, in one status line, under the moving top', () => {
    const html = renderToStaticMarkup(createElement(RestartScreen))
    expect(html).toContain('<p role="status"')
    expect(html).toContain('Applying your changes, back in a moment…')
    expect(html).toMatch(/class="top-hop[^"]*"><div class="top-spin"><svg aria-hidden/)
  })
})
