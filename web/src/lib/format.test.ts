import i18next from 'i18next'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { apiLanguage, languageOf, onLanguageChange, setLanguage, systemLanguage } from '../i18n'
import { formatDate, formatDollars, formatFixed, formatList, formatPrice, formatNumber, formatPercent, formatRecord, formatRelative } from './format'

// Every expected string below was read from Chromium 153's own ICU (the
// browser the screenshots run in) and Node's, which agree: `Intl` called
// directly with `en-US` and `pt-BR`. Portuguese writes the percent sign
// with no space before it, "52%", in both.

// 2026-10-08 18:30 UTC is 14:30 in New York, the zone vitest.config.ts sets.
const MOMENT = Date.UTC(2026, 9, 8, 18, 30)
const MEDIUM: Intl.DateTimeFormatOptions = { dateStyle: 'medium', timeStyle: 'short' }

beforeAll(() => {
  setLanguage('en')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fixed places and dollars', () => {
  it('writes the places toFixed wrote, in English', () => {
    expect(formatFixed(0.12, 3)).toBe('0.120')
    expect(formatFixed(0, 3)).toBe('0.000')
    expect(formatFixed(1234.5678, 3)).toBe('1234.568')
    expect(formatFixed(1234.5, 1)).toBe('1234.5')
    // An exact tie in binary rounds up in both; a value like 1.005 does not (see the report).
    expect(formatFixed(1.005, 2)).toBe('1.01')
    expect(formatFixed(2.5, 0)).toBe((2.5).toFixed(0))
    expect(formatFixed(0.125, 2)).toBe((0.125).toFixed(2))
    expect(formatDollars(1.038)).toBe('$1.038')
    expect(formatPrice(2.5)).toBe('$2.5')
    expect(formatPrice(5)).toBe('$5')
    expect(formatDollars(1000)).toBe('$1000.000')
    expect(formatPrice(1000)).toBe('$1000')
    expect(formatFixed(-0, 1)).toBe((-0).toFixed(1))
    expect(formatFixed(-0, 1)).toBe('0.0')
    expect(formatFixed(-0.01, 1)).toBe((-0.01).toFixed(1))
    expect(formatDollars(0)).toBe('$0.000')
    expect(formatDollars(0.004)).toBe('$0.004')
  })
})

describe('in English', () => {
  it('writes numbers, percentages, dates, relative times and lists as en-US', () => {
    expect(formatNumber(1234.5)).toBe('1,234.5')
    expect(formatPercent(0.52)).toBe('52%')
    expect(formatPercent(0.525, { maximumFractionDigits: 1 })).toBe('52.5%')
    expect(formatDate(MOMENT, MEDIUM)).toBe('Oct 8, 2026, 2:30 PM')
    expect(formatRelative(-1, 'day', { numeric: 'auto' })).toBe('yesterday')
    expect(formatList(['A', 'B', 'C'])).toBe('A, B, and C')
  })
})

describe('in Portuguese', () => {
  it('writes numbers, percentages, dates, relative times and lists as pt-BR', () => {
    // The pt-BR catalogues ship, so Portuguese is a language the text
    // resolves to and the numbers follow it.
    expect(i18next.hasResourceBundle('pt-BR', 'shell')).toBe(true)
    setLanguage('pt-BR')
    expect(formatNumber(1234.5)).toBe('1.234,5')
    expect(formatPercent(0.52)).toBe('52%')
    expect(formatDate(MOMENT, MEDIUM)).toBe('8 de out. de 2026, 14:30')
    expect(formatRelative(-1, 'day', { numeric: 'auto' })).toBe('ontem')
    expect(formatList(['A', 'B', 'C'])).toBe('A, B e C')
    expect(apiLanguage()).toBe('pt-BR')
    setLanguage('en')
  })
})

describe('apiLanguage', () => {
  it('resolves "system" from the browser languages, in their order', () => {
    setLanguage('system')
    vi.stubGlobal('navigator', { languages: ['pt-PT', 'en-US'], language: 'pt-PT' })
    expect(apiLanguage()).toBe('pt-BR')
    vi.stubGlobal('navigator', { languages: ['de-DE', 'pt-BR'], language: 'de-DE' })
    expect(apiLanguage()).toBe('pt-BR')
    vi.stubGlobal('navigator', { languages: ['en-GB', 'pt-BR'], language: 'en-GB' })
    expect(apiLanguage()).toBe('en')
    vi.stubGlobal('navigator', { languages: ['fr-FR'], language: 'fr-FR' })
    expect(apiLanguage()).toBe('en')
    setLanguage('en')
  })

  it('reads navigator.language where there is no list, and English where there is neither', () => {
    vi.stubGlobal('navigator', { language: 'pt' })
    expect(languageOf('system')).toBe('pt-BR')
    vi.stubGlobal('navigator', {})
    expect(languageOf('system')).toBe('en')
  })

  it('answers a language chosen whatever the browser says', () => {
    vi.stubGlobal('navigator', { languages: ['pt-BR'], language: 'pt-BR' })
    setLanguage('en')
    expect(apiLanguage()).toBe('en')
  })
})

describe('systemLanguage', () => {
  it('takes the first language the dashboard has', () => {
    expect(systemLanguage(['pt'])).toBe('pt-BR')
    expect(systemLanguage(['PT-br'])).toBe('pt-BR')
    expect(systemLanguage(['en'])).toBe('en')
    expect(systemLanguage(['es-ES', 'it-IT'])).toBe('en')
    expect(systemLanguage([])).toBe('en')
    // "pt" alone, not a tag that merely starts with the letters.
    expect(systemLanguage(['ptx', 'en'])).toBe('en')
  })
})

describe('onLanguageChange', () => {
  it('is called once per change of the language, not of the choice', () => {
    setLanguage('en')
    const heard: string[] = []
    const stop = onLanguageChange((language) => heard.push(language))
    setLanguage('pt-BR')
    setLanguage('pt-BR')
    vi.stubGlobal('navigator', { languages: ['pt-BR'], language: 'pt-BR' })
    setLanguage('system')
    setLanguage('en')
    stop()
    setLanguage('pt-BR')
    expect(heard).toEqual(['pt-BR', 'en'])
    setLanguage('en')
  })
})

describe('percent bounds and records', () => {
  it('keeps a rate that is neither nothing nor everything off 0% and 100%', () => {
    setLanguage('en')
    expect(formatPercent(0)).toBe('0%')
    expect(formatPercent(0.004)).toBe('<1%')
    expect(formatPercent(0.01)).toBe('1%')
    expect(formatPercent(0.995)).toBe('>99%')
    expect(formatPercent(1)).toBe('100%')
    setLanguage('pt-BR')
    expect(formatPercent(0)).toBe('0%')
    expect(formatPercent(0.004)).toBe('<1%')
    expect(formatPercent(0.01)).toBe('1%')
    expect(formatPercent(0.995)).toBe('>99%')
    expect(formatPercent(1)).toBe('100%')
    setLanguage('en')
  })

  it('writes a record wins, en dash, losses', () => {
    expect(formatRecord(6, 3)).toBe('6\u2060–\u20603')
    expect(formatRecord(1234, 0)).toBe('1,234\u2060–\u20600')
  })
})
