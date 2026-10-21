// node --test worker/platform.test.mjs
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { platform } from './platform.mjs'

const CHROME_WINDOWS =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'
const FIREFOX_LINUX = 'Mozilla/5.0 (X11; Linux x86_64; rv:157.0) Gecko/20100101 Firefox/157.0'
const SAFARI_MAC =
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15'
const CHROME_ANDROID =
  'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Mobile Safari/537.36'
const CHROMIUM_LINUX =
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/154.0.0.0 Safari/537.36'
const CHROME_OS =
  'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'

function ask(agent, hint) {
  const headers = {}
  if (agent !== undefined) headers['User-Agent'] = agent
  if (hint !== undefined) headers['Sec-CH-UA-Platform'] = hint
  return platform(new Request('https://senseitop.com/', { headers }))
}

// [row, expected, hint, user agent, source]
const ROWS = [
  // MDN (Windows 11 reports NT 10.0)
  ['Chrome, Windows 11', 'windows', undefined, CHROME_WINDOWS],
  // MDN + the hint Chromium sends
  ['Chrome, Windows 11, with hint', 'windows', '"Windows"', CHROME_WINDOWS],
  // built: MDN's Firefox Windows 64-bit format, NT 10.0, current version
  ['Firefox, Windows 11', 'windows', undefined, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:157.0) Gecko/20100101 Firefox/157.0'],
  // captured, Chromium 154, Arch Linux
  ['Chromium, Linux (headless)', 'linux', '"Linux"', CHROMIUM_LINUX],
  // captured (hint dropped to test the UA path)
  ['Chromium, Linux, UA only', 'linux', undefined, CHROMIUM_LINUX],
  // captured, Firefox 157, Arch Linux
  ['Firefox, Linux', 'linux', undefined, FIREFOX_LINUX],
  // built: Firefox's Linux x86_64 format (MDN), which SteamOS's Firefox sends; not captured on a Deck
  ['Firefox, Steam Deck desktop mode', 'linux', undefined, FIREFOX_LINUX],
  // MDN
  ['Safari, macOS', 'mac', undefined, SAFARI_MAC],
  // MDN
  ['Chrome, macOS, with hint', 'mac', '"macOS"', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'],
  // iPadOS Safari sends the macOS string by default (D7: mac, not phone)
  ['Safari, iPadOS (desktop mode)', 'mac', undefined, SAFARI_MAC],
  // MDN
  ['Chrome, Android phone', 'phone', undefined, CHROME_ANDROID],
  // MDN + hint
  ['Chrome, Android phone, with hint', 'phone', '"Android"', CHROME_ANDROID],
  // Chromium (no `Mobile`; `Android` decides)
  ['Chrome, Android tablet', 'phone', undefined, 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.0.0 Safari/537.36'],
  // MDN
  ['Safari, iPhone', 'phone', undefined, 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Mobile/15E148 Safari/604.1'],
  // built: Chromium's CrOS token in the reduced format
  ['Chrome, ChromeOS', null, undefined, CHROME_OS],
  // built + hint
  ['Chrome, ChromeOS, with hint', null, '"Chrome OS"', CHROME_OS],
  // none: no User-Agent header
  ['Empty', null, undefined, undefined],
  // captured UA, hint set by the test: the hint wins
  ['Hint disagrees', 'windows', '"Windows"', CHROMIUM_LINUX],
  // an unrecognized hint gives null and the UA is not consulted
  ['Unknown hint', null, '"Fuchsia"', CHROMIUM_LINUX],
  // MDN
  ['curl', null, undefined, 'curl/7.64.1'],
]

test('each browser string maps to its system', () => {
  for (const [row, expected, hint, agent] of ROWS) {
    assert.equal(ask(agent, hint), expected, row)
  }
})

test('a hint named like an Object property is unknown', () => {
  for (const hint of ['"toString"', '"__proto__"']) assert.equal(ask(CHROMIUM_LINUX, hint), null, hint)
})
