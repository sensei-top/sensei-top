import i18next from 'i18next'
import { beforeAll } from 'vitest'
import './src/i18n'

// The global i18next instance follows the machine's language by default
// (`ago()` and anything else reading `currentT()`); a test's English must not
// depend on LANG, so every test file starts in English.
beforeAll(async () => {
  await i18next.changeLanguage('en')
})
