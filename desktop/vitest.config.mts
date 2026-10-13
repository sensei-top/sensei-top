import { defineConfig } from 'vitest/config';

// The tests run from src/ and scripts/, never the copies tsc writes into dist/.
export default defineConfig({
  test: {
    include: ['src/**/*.test.ts', 'scripts/**/*.test.ts'],
    environment: 'node',
  },
});
