import { describe, expect, it } from 'vitest'
import { writerFrom } from './writer'

describe('writerFrom', () => {
  it('lets a key write', () => {
    expect(writerFrom({ configured: true })).toEqual({ by: 'key' })
  })

  it('has nobody write with no key', () => {
    expect(writerFrom({ configured: false })).toEqual({ by: 'nobody' })
  })

  it('has nobody write before the key status answers', () => {
    expect(writerFrom(undefined)).toEqual({ by: 'nobody' })
    expect(writerFrom(null)).toEqual({ by: 'nobody' })
  })
})
