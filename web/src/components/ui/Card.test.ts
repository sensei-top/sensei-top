import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { NoteMarkerContext } from '../../lib/noteMarker'
import { Prose } from './Card'

const known = (n: string) => (n === '2' ? createElement('b', { 'data-chip': n }, `chip ${n}`) : null)

function draw(text: string, render = known) {
  return renderToStaticMarkup(
    createElement(NoteMarkerContext.Provider, { value: render }, createElement(Prose, { text })),
  )
}

describe('Prose note markers', () => {
  it('draws the renderer for a known [N<n>]', () => {
    const html = draw('Hold priority [N2] here.')
    expect(html).toContain('<b data-chip="2">chip 2</b>')
    expect(html).not.toContain('[N2]')
  })

  it('draws nothing for an unknown [N<n>]', () => {
    const html = draw('Hold priority [N9] here.')
    expect(html).not.toContain('[N9]')
    expect(html).not.toContain('chip')
    expect(html).toContain('Hold priority')
  })

  it('draws nothing without a provider, and keeps bold and code', () => {
    const html = renderToStaticMarkup(createElement(Prose, { text: '**a** [N2] `b`' }))
    expect(html).not.toContain('[N2]')
    expect(html).toContain('<strong')
    expect(html).toContain('<code')
  })
})
