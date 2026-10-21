// Which system a visitor's browser says it runs on, so the landing can put
// that system's installer first. It reads two request headers and nothing
// else: `Sec-CH-UA-Platform`, which Chromium sends by default over HTTPS, and
// otherwise the platform token in `User-Agent`. The Worker never sends
// `Accept-CH`, so no high-entropy hint is asked for. The answer is not
// stored or logged.

const HINTS = {
  Windows: 'windows',
  Linux: 'linux',
  macOS: 'mac',
  Android: 'phone',
  iOS: 'phone',
}

// The order is the rule: Android's UA contains `Linux`, and iPadOS's contains
// `Macintosh`.
const TOKENS = [
  [/Android|iPhone|iPad|Mobile/, 'phone'],
  [/Windows NT/, 'windows'],
  [/CrOS/, null],
  [/Macintosh/, 'mac'],
  [/Linux|X11/, 'linux'],
]

/** 'windows', 'linux', 'mac', 'phone', or null when the system is unknown or ChromeOS. */
export function platform(request) {
  const hint = request.headers.get('Sec-CH-UA-Platform')
  if (hint) {
    const value = hint.trim().replace(/^"|"$/g, '')
    return Object.hasOwn(HINTS, value) ? HINTS[value] : null
  }
  const agent = request.headers.get('User-Agent') ?? ''
  for (const [pattern, os] of TOKENS) if (pattern.test(agent)) return os
  return null
}
