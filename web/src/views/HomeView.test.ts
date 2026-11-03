import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import '../i18n'
import { AiFeaturesContext } from '../shell/aiFeatures'
import { FieldAndCoach } from './HomeView'

function draw(aiOn: boolean, field: string | null): string {
  return renderToStaticMarkup(
    createElement(
      AiFeaturesContext.Provider,
      { value: aiOn },
      createElement(
        MemoryRouter,
        null,
        createElement(FieldAndCoach, { field: field ? createElement('p', null, field) : null }),
      ),
    ),
  )
}

describe('the field beside the coach', () => {
  it('shows the coach\'s pointer, and its link, with AI features on', () => {
    const html = draw(true, 'the field')
    expect(html).toContain('href="/coach"')
    expect(html).toContain('the field')
  })

  it('drops the pointer when off and gives the field the row', () => {
    const html = draw(false, 'the field')
    expect(html).not.toContain('/coach')
    expect(html).toContain('lg:col-span-3')
    expect(html).toContain('the field')
  })

  it('draws nothing when off and there is no field', () => {
    expect(draw(false, null)).toBe('')
  })
})
