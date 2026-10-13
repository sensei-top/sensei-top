/** What the credits view shows, as data: the names, the addresses and the
 *  notices that are not ours to reword stay here as written; every sentence
 *  of the app's own is a key into `locales/en/credits.json`, which the view
 *  reads with `t`. `docs/attribution.md` stays the authority: a new source
 *  gets its row there and its entry here in the same change. Wizards' notice
 *  is not here: it has one home, `welcome.intro.wizardsNotice`, verbatim
 *  (Fan Content Policy) and on one line, which `tests/test_attribution.py`
 *  compares against the other places that carry it. */

/** A key of `locales/en/credits.json`, written in full, `credits.…`. */
type Key = string

export interface CreditLink {
  /** The licence's name, as the licence writes it: not translated. */
  text: string
  url: string
}

export interface DataSourceCredit {
  /** Shown as the link to `url`. */
  name: string
  url: string
  taken: Key
  terms: Key
  /** Where `terms` links to; `null` shows the terms as plain text. */
  termsUrl: string | null
}

export interface FontCredit {
  /** Shown as the link to `url`. */
  name: string
  /** Who made it, when the name alone does not say: drawn as
   *  "`name`, by `author`" through `credits.fonts.byAuthor`. */
  author?: string
  url: string
  usedFor: Key
  /** The copyright notice, as the font's authors wrote it: not translated. */
  notice: string
}

export interface SoftwareCredit {
  /** The work's name, a key: four of the six are phrases of ours ("Desktop
   *  app libraries"), so every catalogue carries all six, a proper noun
   *  unchanged. Shown as the link to `url`; `null` shows it unlinked. */
  name: Key
  url: string | null
  usedFor: Key
  /** A copyright line the work's authors wrote, shown before `notice`: not translated. */
  copyright?: string
  notice: Key
  /** The entry the dashboard's own notices open under, from
   *  `third-party-notices.txt` (web/scripts/thirdPartyNotices.ts). */
  showsNotices?: boolean
}

/** The public repository's address. The view shows its "Source code" link
 *  only when this is set, and nothing in its place otherwise. */
export const sourceUrl: string | null = 'https://github.com/sensei-top/sensei-top'

export const credits = {
  wizards: {
    heading: 'Wizards of the Coast',
    /** The paragraphs after Wizards' notice, which `CreditsView` draws first
     *  from `welcome.intro.wizardsNotice`. */
    paragraphs: ['credits.wizards.reads', 'credits.wizards.images'] as Key[],
  },

  dataSources: {
    heading: 'credits.dataSources.heading',
    opening: 'credits.dataSources.opening',
    entries: [
      {
        name: 'Scryfall',
        url: 'https://scryfall.com',
        taken: 'credits.dataSources.entries.scryfall.taken',
        terms: 'credits.dataSources.entries.scryfall.terms',
        termsUrl: 'https://scryfall.com/docs/api',
      },
      {
        name: 'MTGOFormatData',
        url: 'https://github.com/Badaro/MTGOFormatData',
        taken: 'credits.dataSources.entries.mtgoFormatData.taken',
        terms: 'credits.dataSources.entries.mtgoFormatData.terms',
        termsUrl: null,
      },
      {
        name: 'MTG_decklistcache',
        url: 'https://github.com/fbettega/MTG_decklistcache',
        taken: 'credits.dataSources.entries.decklistCache.taken',
        terms: 'credits.dataSources.entries.decklistCache.terms',
        termsUrl: null,
      },
      {
        name: 'TopDeck.gg',
        url: 'https://topdeck.gg',
        taken: 'credits.dataSources.entries.topdeck.taken',
        terms: 'credits.dataSources.entries.topdeck.terms',
        termsUrl: 'https://topdeck.gg/docs/tournaments-v2',
      },
      {
        name: 'mtgo.com',
        url: 'https://www.mtgo.com/decklists',
        taken: 'credits.dataSources.entries.mtgo.taken',
        terms: 'credits.dataSources.entries.mtgo.terms',
        termsUrl: null,
      },
      {
        name: 'Anthropic',
        url: 'https://www.anthropic.com',
        taken: 'credits.dataSources.entries.anthropic.taken',
        terms: 'credits.dataSources.entries.anthropic.terms',
        termsUrl: null,
      },
    ] satisfies DataSourceCredit[],
    closing: 'credits.dataSources.closing',
  },

  fonts: {
    heading: 'credits.fonts.heading',
    opening: 'credits.fonts.opening',
    entries: [
      {
        name: 'Mana',
        author: 'Andrew Gioia',
        url: 'https://github.com/andrewgioia/mana',
        usedFor: 'credits.fonts.entries.mana.usedFor',
        notice: 'Glyphs under SIL OFL 1.1. Mana symbol imagery © Wizards of the Coast.',
      },
      {
        name: 'Bricolage Grotesque',
        url: 'https://github.com/ateliertriay/bricolage',
        usedFor: 'credits.fonts.entries.bricolage.usedFor',
        notice:
          'SIL OFL 1.1. Copyright 2022 The Bricolage Grotesque Project Authors (https://github.com/ateliertriay/bricolage)',
      },
      {
        name: 'Hanken Grotesk',
        url: 'https://github.com/marcologous/hanken-grotesk',
        usedFor: 'credits.fonts.entries.hanken.usedFor',
        notice:
          'SIL OFL 1.1. Copyright 2021 The Hanken Grotesk Project Authors (https://github.com/marcologous/hanken-grotesk)',
      },
    ] satisfies FontCredit[],
    licence: {
      text: 'SIL Open Font License 1.1',
      url: 'https://openfontlicense.org',
    } satisfies CreditLink,
  },

  software: {
    heading: 'credits.software.heading',
    opening: 'credits.software.opening',
    entries: [
      {
        name: 'credits.software.entries.electron.name',
        url: 'https://www.electronjs.org',
        usedFor: 'credits.software.entries.electron.usedFor',
        notice: 'credits.software.entries.electron.notice',
      },
      {
        name: 'credits.software.entries.desktop.name',
        url: null,
        usedFor: 'credits.software.entries.desktop.usedFor',
        notice: 'credits.software.entries.desktop.notice',
      },
      {
        name: 'credits.software.entries.python.name',
        url: 'https://www.python.org',
        copyright: 'Copyright © 2001 Python Software Foundation; All Rights Reserved.',
        usedFor: 'credits.software.entries.python.usedFor',
        notice: 'credits.software.entries.python.notice',
      },
      {
        name: 'credits.software.entries.pythonLibraries.name',
        url: 'https://pypi.org',
        usedFor: 'credits.software.entries.pythonLibraries.usedFor',
        notice: 'credits.software.entries.pythonLibraries.notice',
      },
      {
        name: 'credits.software.entries.dashboard.name',
        url: null,
        usedFor: 'credits.software.entries.dashboard.usedFor',
        notice: 'credits.software.entries.dashboard.notice',
        showsNotices: true,
      },
      {
        name: 'credits.software.entries.pyinstaller.name',
        url: 'https://pyinstaller.org',
        usedFor: 'credits.software.entries.pyinstaller.usedFor',
        notice: 'credits.software.entries.pyinstaller.notice',
      },
    ] satisfies SoftwareCredit[],
    /** The notices disclosure: fetched from the dashboard's own origin the
     *  first time it opens, shown in place, since a link would replace the
     *  dashboard in the desktop app's window, which has no back button. */
    notices: {
      path: '/third-party-notices.txt',
      show: 'credits.software.notices.show',
      hide: 'credits.software.notices.hide',
      loading: 'credits.software.notices.loading',
      failed: 'credits.software.notices.failed',
    },
  },

  program: {
    heading: 'Sensei Top',
    paragraphs: [
      'credits.program.copyright',
      'credits.program.free',
      'credits.program.copy',
      'credits.program.name',
    ] as Key[],
    licence: {
      text: 'GNU Affero General Public License, version 3',
      url: 'https://www.gnu.org/licenses/agpl-3.0.html',
    } satisfies CreditLink,
    sourceLinkText: 'credits.program.sourceLink',
  },
}
