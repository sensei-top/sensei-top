import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { OutlineCard } from './Outline'

describe('OutlineCard', () => {
  it('holds the words in one status inside its frame, under its label', () => {
    const html = renderToStaticMarkup(
      createElement(OutlineCard, { label: 'Games', words: 'Reading your matches…', height: 'h-24' }),
    )
    expect(html.match(/role="status"/g)).toHaveLength(1)
    expect(html).toMatch(/role="status"[^>]*>Reading your matches…<\/div>/)
    expect(html).toContain('Games')
    expect(html).not.toContain('<h3')
  })

  it('has no status without words', () => {
    const html = renderToStaticMarkup(createElement(OutlineCard, { height: 'h-48' }))
    expect(html).not.toContain('role="status"')
  })

  it('puts children in the same single status in place of the words', () => {
    const html = renderToStaticMarkup(
      createElement(OutlineCard, { words: 'Reading…', height: 'h-24' }, createElement('ol', null, 'Stages')),
    )
    expect(html.match(/role="status"/g)).toHaveLength(1)
    expect(html).toMatch(/role="status"[^>]*><ol>Stages<\/ol><\/div>/)
    expect(html).not.toContain('Reading…')
  })
})
