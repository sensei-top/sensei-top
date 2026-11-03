import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { IntermissionOut } from '../api'
import { AiFeaturesContext } from '../shell/aiFeatures'
import { SideboardPlanCard } from './SideboardPlanCard'

function intermission(change: Partial<IntermissionOut> = {}): IntermissionOut {
  return {
    game_number: 1,
    next_game: 2,
    won: false,
    stale: false,
    cards_seen: 0,
    plan: null,
    prompt: null,
    opponent: null,
    fmt: 'Modern',
    past_boarding: [],
    ...change,
  } as unknown as IntermissionOut
}

function draw(data: IntermissionOut, aiOn: boolean): string {
  return renderToStaticMarkup(
    createElement(
      AiFeaturesContext.Provider,
      { value: aiOn },
      createElement(SideboardPlanCard, { intermission: data, match: null }),
    ),
  )
}

describe('SideboardPlanCard with AI features off', () => {
  it('says nothing has been boarded when there is no past boarding', () => {
    const html = draw(intermission(), false)
    expect(html).toContain('You haven&#x27;t boarded in this matchup yet.')
    expect(html).not.toContain('No written plan')
  })

  it('says it even when a plan exists but is hidden', () => {
    const html = draw(intermission({ prompt: 'write a plan' }), false)
    expect(html).toContain('You haven&#x27;t boarded in this matchup yet.')
  })

  it.each(['exact', 'closest'])('hides a %s plan: no prose, no closest line, the message shows', (basis) => {
    const plan = {
      archetype_key: 'x',
      archetype_label: 'X',
      prose: 'SECRET PLAN PROSE',
      board_in: [{ card: 'Negate', n: 2 }],
      board_out: [],
      problems: [],
      play_around: [],
    }
    const html = draw(intermission({ plan, plan_basis: basis, plan_archetype_label: 'X' } as never), false)
    expect(html).toContain('You haven&#x27;t boarded in this matchup yet.')
    expect(html).not.toContain('SECRET PLAN PROSE')
    expect(html).not.toContain('Negate')
    expect(html).not.toContain('closest')
  })

  it('draws the past boarding instead of the message', () => {
    const data = intermission({
      past_boarding: [
        {
          match_id: 'm1',
          games: [
            {
              game_number: 2,
              board_in: [{ grp_id: 1, card: 'Island', n: 2, in_current_75: true }],
              board_out: [],
              result: 'win',
            },
          ],
        },
      ],
    })
    const html = draw(data, false)
    expect(html).toContain('Island')
    expect(html).not.toContain('boarded in this matchup yet')
  })

  it('keeps the on state\'s message', () => {
    const html = draw(intermission({ opponent: { archetype_key: 'x' } as never }), true)
    expect(html).toContain('No written plan for this matchup, and nothing to write one from.')
  })
})
