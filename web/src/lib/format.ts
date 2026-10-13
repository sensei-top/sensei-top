import i18next from 'i18next'

/**
 * Numbers, percentages, dates, relative times and lists, through `Intl`,
 * in the language the dashboard is read in. Every number or date a page
 * shows goes through here, so it reads the way its sentence does.
 *
 * The locale follows the language the text actually resolved to
 * (`resolvedLanguage`), not the one chosen: a language with no catalogue
 * yet reads as English, and its numbers and dates read as English with it.
 * English is `en-US`, as the dashboard has always written it. Before
 * `i18n.ts` has started (a test of a function that formats), it is `en-US`
 * too.
 */

/** The `Intl` locale of the active language. */
export function formatLocale(): string {
  return i18next.resolvedLanguage?.startsWith('pt') ? 'pt-BR' : 'en-US'
}

// Building a formatter costs more than using one, so each is built once per
// locale and options.
const built = new Map<string, unknown>()

function cached<T>(kind: string, options: object | undefined, make: (locale: string) => T): T {
  const locale = formatLocale()
  const key = `${kind}|${locale}|${JSON.stringify(options ?? {})}`
  let formatter = built.get(key) as T | undefined
  if (formatter === undefined) {
    formatter = make(locale)
    built.set(key, formatter)
  }
  return formatter
}

/** "1,234.5" in English, "1.234,5" in Portuguese. */
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return cached('number', options, (locale) => new Intl.NumberFormat(locale, options)).format(value)
}

/** A share or a rate, 0..1, with its sign: "52%". Whole by default;
 *  `options` may ask for digits. */
export function formatPercent(fraction: number, options?: Intl.NumberFormatOptions): string {
  const all: Intl.NumberFormatOptions = { style: 'percent', maximumFractionDigits: 0, ...options }
  return cached('percent', all, (locale) => new Intl.NumberFormat(locale, all)).format(fraction)
}

/** A moment, in the viewer's own zone, in the shape `options` asks for. */
export function formatDate(moment: number | Date, options?: Intl.DateTimeFormatOptions): string {
  return cached('date', options, (locale) => new Intl.DateTimeFormat(locale, options)).format(moment)
}

/** "yesterday", "in 3 days", "5 minutes ago": `value` units from now, a
 *  negative value in the past. */
export function formatRelative(
  value: number,
  unit: Intl.RelativeTimeFormatUnit,
  options?: Intl.RelativeTimeFormatOptions,
): string {
  return cached('relative', options, (locale) => new Intl.RelativeTimeFormat(locale, options)).format(value, unit)
}

/** "A, B, and C" in English, "A, B e C" in Portuguese. */
export function formatList(items: readonly string[], options?: Intl.ListFormatOptions): string {
  return cached('list', options, (locale) => new Intl.ListFormat(locale, options)).format(items)
}

/** `value` to exactly `digits` places, as `toFixed` writes it but in the
 *  language's own separators: "0.120" in English, "0,120" in Portuguese.
 *  Never grouped, as `toFixed` never is. */
export function formatFixed(value: number, digits: number): string {
  // `toFixed` writes -0 as "0"; `Intl` writes "-0". A tiny negative that
  // rounds to zero is "-0.0" in both.
  const zero = Object.is(value, -0) ? 0 : value
  return formatNumber(zero, { minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping: false })
}

/** A cost in US dollars to three places: "$0.120", "$1.038" in English,
 *  "US$ 0,120" in Portuguese. The places are fixed, so 0 reads "$0.000". */
export function formatDollars(cost: number): string {
  const options: Intl.NumberFormatOptions = {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
    useGrouping: false,
  }
  return cached('dollars', options, (locale) => new Intl.NumberFormat(locale, options)).format(cost)
}

/** A price in US dollars with only the places it needs, up to three:
 *  "$2.5", "$12.5", "$5". */
export function formatPrice(price: number): string {
  const options: Intl.NumberFormatOptions = {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 3,
    useGrouping: false,
  }
  return cached('price', options, (locale) => new Intl.NumberFormat(locale, options)).format(price)
}
