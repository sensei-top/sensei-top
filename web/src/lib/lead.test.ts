import { describe, expect, it } from 'vitest'
import { leadOf } from './lead'

describe('leadOf', () => {
  it('prefers the stored lead, trimmed', () => {
    expect(leadOf('  Mulligan less.  ', 'Something else. Entirely.')).toBe('Mulligan less.')
  })

  it('falls back on a blank or missing lead', () => {
    expect(leadOf(null, 'First one. Second one.')).toBe('First one.')
    expect(leadOf('   ', 'Really? Yes. Fine.')).toBe('Really?')
    expect(leadOf(undefined, 'Stop! Go on.')).toBe('Stop!')
  })

  it('does not cut before a lowercase letter or inside e.g. / i.e.', () => {
    expect(leadOf('', 'Keep hands with 2 lands, e.g. Plains and Island. Mulligan the rest.')).toBe(
      'Keep hands with 2 lands, e.g. Plains and Island.',
    )
    expect(leadOf('', 'Hold cheap spells, i.e. Shock. Then pass.')).toBe('Hold cheap spells, i.e. Shock.')
    expect(leadOf('', 'It costs 1.5 mana. ok then. Done.')).toBe('It costs 1.5 mana. ok then.')
  })

  it('skips a leading heading and drops emphasis', () => {
    expect(leadOf('', '## Plan\n\nBoard **in** the *sweepers*. Then wait.')).toBe('Board in the sweepers.')
  })

  it('keeps a literal marker and an underscore, drops a citation', () => {
    expect(leadOf('', 'Hit 4*2 and snake_case early [R2]. Then wait.')).toBe('Hit 4*2 and snake_case early.')
  })

  it('cuts before an accented capital', () => {
    expect(leadOf('', 'Isso é bom. É melhor.')).toBe('Isso é bom.')
  })

  it('does not cut at vs.', () => {
    expect(leadOf('', 'Hold removal vs. Rakdos. Then race.')).toBe('Hold removal vs. Rakdos.')
  })

  it('caps at 200 characters at a word boundary', () => {
    const out = leadOf('', 'word '.repeat(80).trim())
    expect(out.length).toBeLessThanOrEqual(200)
    expect(out.endsWith('…')).toBe(true)
    expect(out.slice(0, -1).endsWith('word')).toBe(true)
  })

  it('leaves a short sentence alone', () => {
    expect(leadOf('', 'Short.')).toBe('Short.')
  })
})
