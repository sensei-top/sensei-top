import { describe, expect, it } from 'vitest'
import { sizeOf } from './size'

describe('sizeOf', () => {
  it('says megabytes to one decimal under 100 MB', () => {
    expect(sizeOf(41_300_000)).toBe('41.3 MB')
  })

  it('says whole megabytes from 100 MB', () => {
    expect(sizeOf(412_000_000)).toBe('412 MB')
  })

  it('says gigabytes to one decimal from 1 GB', () => {
    expect(sizeOf(1_200_000_000)).toBe('1.2 GB')
  })

  it('drops a trailing ".0" from gigabytes', () => {
    expect(sizeOf(2_000_000_000)).toBe('2 GB')
  })

  it('says 0.1 MB under 0.1 MB', () => {
    expect(sizeOf(40_000)).toBe('0.1 MB')
  })
})
