import { defineConfig } from 'vitest/config'

// Apart from vite.config.ts on purpose: the tests are of pure functions
// (src/lib, and the build's third-party notices in scripts/), so they need
// neither the React nor the Tailwind plugin, and no DOM.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'scripts/**/*.test.ts'],
    // Weeks and days are counted in the viewer's zone, so the tests fix one:
    // not UTC, where a bare timestamp read as local time would pass by
    // accident, and one whose clocks change, at 02:00.
    env: { TZ: 'America/New_York' },
  },
})
