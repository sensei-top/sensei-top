import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { AiFeaturesContext } from '../shell/aiFeatures'
import { CoachPage } from './CoachPage'

// A static render does not follow a redirect, so it is drawn as a line.
vi.mock('react-router', async (original) => ({
  ...(await original<typeof import('react-router')>()),
  Navigate: ({ to }: { to: string }) => createElement('p', null, `navigate:${to}`),
}))

function draw(aiOn: boolean, path: string): string {
  return renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: new QueryClient() },
      createElement(
        AiFeaturesContext.Provider,
        { value: aiOn },
        createElement(
          MemoryRouter,
          { initialEntries: [path] },
          createElement(
            Routes,
            null,
            createElement(Route, { path: '/coach', Component: CoachPage }),
            createElement(Route, { path: '/coach/:id', Component: CoachPage }),
          ),
        ),
      ),
    ),
  )
}

describe('CoachPage', () => {
  it('goes Home from /coach and from one report when AI features are off', () => {
    expect(draw(false, '/coach')).toContain('navigate:/')
    expect(draw(false, '/coach/3')).toContain('navigate:/')
  })

  it('does not redirect when they are on', () => {
    expect(draw(true, '/coach')).not.toContain('navigate:')
    expect(draw(true, '/coach/3')).not.toContain('navigate:')
  })
})
