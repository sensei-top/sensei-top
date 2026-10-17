import { describe, expect, it } from 'vitest'
import { scrollEdge, spyCurrent } from './scrollSpy'

describe('scrollEdge', () => {
  // A page 3,000 px tall in a window 800 px tall: its end is at scrollY 2,200.
  it('is the top when the window is not scrolled', () => {
    expect(scrollEdge(0, 800, 3000)).toBe('top')
  })

  it('is the end at the last scroll position, and within 2 px of it', () => {
    expect(scrollEdge(2200, 800, 3000)).toBe('end')
    expect(scrollEdge(2198, 800, 3000)).toBe('end')
  })

  it('is neither 3 px short of the end, nor 1 px down from the top', () => {
    expect(scrollEdge(2197, 800, 3000)).toBeNull()
    expect(scrollEdge(1, 800, 3000)).toBeNull()
  })

  it('is the top for a page that fits the window', () => {
    expect(scrollEdge(0, 800, 600)).toBe('top')
  })
})

describe('spyCurrent', () => {
  const ids = ['guide-scope', 'guide-the-list', 'guide-write']

  it("is the observer's answer between the ends", () => {
    expect(spyCurrent(ids, 'guide-the-list', null)).toBe('guide-the-list')
  })

  it('is the first id at the top, whatever the observer said last', () => {
    expect(spyCurrent(ids, 'guide-the-list', 'top')).toBe('guide-scope')
  })

  it('is the last id at the end, whatever the observer said last', () => {
    expect(spyCurrent(ids, 'guide-the-list', 'end')).toBe('guide-write')
  })

  it("is the observer's answer with no ids", () => {
    expect(spyCurrent([], '', 'end')).toBe('')
  })
})
