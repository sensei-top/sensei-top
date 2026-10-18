import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { rateAndRecordLine, rateOrRecord } from './sample'

const t = translator('en')

describe('rateOrRecord', () => {
  it('is a rate and its record from ten finished', () => {
    expect(rateOrRecord({ wins: 6, losses: 4 }, t)).toEqual({ figure: '60%', line: '6\u2060–\u20604', thin: false })
    expect(rateOrRecord({ wins: 35, losses: 25 }, t)).toEqual({ figure: '58%', line: '35\u2060–\u206025', thin: false })
  })

  it('is the muted record at nine', () => {
    expect(rateOrRecord({ wins: 6, losses: 3 }, t)).toEqual({
      figure: '6\u2060–\u20603',
      line: 'too few for a rate, under 10 matches',
      thin: true,
    })
  })

  it('reads games in its own words', () => {
    expect(rateOrRecord({ wins: 1, losses: 0 }, t, 'games').line).toBe('too few for a rate, under 10 games')
  })

  it('has no figure with nothing finished', () => {
    expect(rateOrRecord({ wins: 0, losses: 0 }, t)).toEqual({ figure: null, line: 'no finished match yet', thin: false })
    expect(rateOrRecord({ wins: 0, losses: 0 }, t, 'games').line).toBe('no finished game yet')
  })
})

describe('rateAndRecordLine', () => {
  it('is rate and record from ten, the record alone under, null for none', () => {
    expect(rateAndRecordLine({ wins: 35, losses: 25 })).toBe('58% · 35\u2060–\u206025')
    expect(rateAndRecordLine({ wins: 5, losses: 5 })).toBe('50% · 5\u2060–\u20605')
    expect(rateAndRecordLine({ wins: 6, losses: 3 })).toBe('6\u2060–\u20603')
    expect(rateAndRecordLine({ wins: 0, losses: 0 })).toBeNull()
  })
})
