import { describe, expect, it } from 'vitest'
import { translator } from '../i18n'
import { rateAndRecordLine, rateCell, rateOrRecord } from './sample'

const t = translator('en')

describe('rateOrRecord', () => {
  it('is a rate and its record from ten finished', () => {
    expect(rateOrRecord({ wins: 6, losses: 4 }, t)).toEqual({ figure: '60%', line: '6\u2060–\u20604', thin: false })
    expect(rateOrRecord({ wins: 35, losses: 25 }, t)).toEqual({ figure: '58%', line: '35\u2060–\u206025', thin: false })
  })

  it('is the muted rate and a rough line from five to nine', () => {
    expect(rateOrRecord({ wins: 6, losses: 3 }, t)).toEqual({
      figure: '67%',
      line: '6\u2060–\u20603 · rough, under 10\u00a0matches',
      thin: true,
    })
    expect(rateOrRecord({ wins: 3, losses: 2 }, t, 'games')).toEqual({
      figure: '60%',
      line: '3\u2060–\u20602 · rough, under 10\u00a0games',
      thin: true,
    })
  })

  it('is the muted record at four', () => {
    expect(rateOrRecord({ wins: 3, losses: 1 }, t)).toEqual({
      figure: '3\u2060–\u20601',
      line: 'too few for a rate, under 5\u00a0matches',
      thin: true,
    })
  })

  it('reads games in its own words', () => {
    expect(rateOrRecord({ wins: 1, losses: 0 }, t, 'games').line).toBe('too few for a rate, under 5\u00a0games')
  })

  it('has no figure with nothing finished', () => {
    expect(rateOrRecord({ wins: 0, losses: 0 }, t)).toEqual({ figure: null, line: 'no finished match yet', thin: false })
    expect(rateOrRecord({ wins: 0, losses: 0 }, t, 'games').line).toBe('no finished game yet')
  })
})

describe('rateCell', () => {
  it('is the rate from ten, muted from five to nine, "too few" muted under five, null for none', () => {
    expect(rateCell({ wins: 6, losses: 4 }, t)).toEqual({ text: '60%', muted: false })
    expect(rateCell({ wins: 6, losses: 3 }, t)).toEqual({ text: '67%', muted: true })
    expect(rateCell({ wins: 3, losses: 2 }, t, 'games')).toEqual({ text: '60%', muted: true })
    expect(rateCell({ wins: 3, losses: 1 }, t)).toEqual({ text: 'too few', muted: true })
    expect(rateCell({ wins: 0, losses: 0 }, t)).toBeNull()
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
