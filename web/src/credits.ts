/** Every sentence the footer's notice and the credits view show, as data.
 *  `CreditsView` renders this and holds no wording of its own beyond its
 *  controls. `docs/attribution.md` stays the authority: a new source gets
 *  its row there and its entry here in the same change. Wizards' notice is
 *  verbatim (Fan Content Policy) and stays on one line, so it can be
 *  compared byte for byte against the other places that carry it. */

export interface CreditLink {
  text: string
  url: string
}

export interface DataSourceCredit {
  /** Shown as the link to `url`. */
  name: string
  url: string
  taken: string
  terms: string
  /** Where `terms` links to; `null` shows the terms as plain text. */
  termsUrl: string | null
}

export interface FontCredit {
  /** Shown as the link to `url`. */
  name: string
  url: string
  usedFor: string
  notice: string
}

export const wizardsNotice =
  'Sensei Top is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.'

export const credits = {
  wizards: {
    heading: 'Wizards of the Coast',
    paragraphs: [
      wizardsNotice,
      'Sensei Top reads the log files Magic: The Gathering Arena and Magic Online write on this machine. It changes neither client and reads nothing from their memory.',
      'Card images are shown whole. Where card art appears on its own, the button in its corner shows the whole card, which carries the artist\'s name and the copyright line.',
    ],
  },

  dataSources: {
    heading: 'Data sources',
    opening:
      'Sensei Top bundles none of this data. Each installed copy downloads what it needs to the machine it runs on.',
    entries: [
      {
        name: 'Scryfall',
        url: 'https://scryfall.com',
        taken: 'Card names, rules text, legality, card images and card art.',
        terms: "Used under Scryfall's API terms.",
        termsUrl: 'https://scryfall.com/docs/api',
      },
      {
        name: 'MTGOFormatData',
        url: 'https://github.com/Badaro/MTGOFormatData',
        taken:
          "The archetype definitions that name an opponent's deck. Jiliac's fork is the fallback when the first repository cannot be reached.",
        terms: 'Neither repository carries a licence file.',
        termsUrl: null,
      },
      {
        name: 'MTG_decklistcache',
        url: 'https://github.com/fbettega/MTG_decklistcache',
        taken: 'MTGO and Melee tournament results for the Field page.',
        terms: 'GPL-3.0. Downloaded by each copy, never bundled or redistributed by this project.',
        termsUrl: null,
      },
      {
        name: 'TopDeck.gg',
        url: 'https://topdeck.gg',
        taken: 'Tournament results, through their API and your own free key.',
        terms: "Used under TopDeck.gg's API terms.",
        termsUrl: 'https://topdeck.gg/docs/tournaments-v2',
      },
      {
        name: 'Anthropic',
        url: 'https://www.anthropic.com',
        taken: 'The Claude API, only when you configure a key and press a generate button.',
        terms: "Your own account and key, under Anthropic's terms.",
        termsUrl: null,
      },
    ] satisfies DataSourceCredit[],
    closing:
      'Sensei Top is not produced by, endorsed by or affiliated with Scryfall, TopDeck.gg, Anthropic, or the maintainers of MTGOFormatData and MTG_decklistcache. Their names appear here to credit their work.',
  },

  fonts: {
    heading: 'Fonts and symbols',
    opening:
      'These ship inside the dashboard. Each is listed with its copyright notice, and the licence is linked below.',
    entries: [
      {
        name: 'Mana, by Andrew Gioia',
        url: 'https://github.com/andrewgioia/mana',
        usedFor: 'The mana symbol glyphs.',
        notice: 'Glyphs under SIL OFL 1.1. Mana symbol imagery © Wizards of the Coast.',
      },
      {
        name: 'Bricolage Grotesque',
        url: 'https://github.com/ateliertriay/bricolage',
        usedFor: 'Headings and headline numbers.',
        notice:
          'SIL OFL 1.1. Copyright 2022 The Bricolage Grotesque Project Authors (https://github.com/ateliertriay/bricolage)',
      },
      {
        name: 'Hanken Grotesk',
        url: 'https://github.com/marcologous/hanken-grotesk',
        usedFor: 'Interface text and numbers.',
        notice:
          'SIL OFL 1.1. Copyright 2021 The Hanken Grotesk Project Authors (https://github.com/marcologous/hanken-grotesk)',
      },
    ] satisfies FontCredit[],
    licence: {
      text: 'SIL Open Font License 1.1',
      url: 'https://openfontlicense.org',
    } satisfies CreditLink,
  },

  program: {
    heading: 'Sensei Top',
    paragraphs: [
      'Copyright (C) 2026 The Sensei Top maintainer. All rights reserved.',
      'Sensei Top is proprietary software, free to install and use. It comes with no warranty.',
      "The Sensei Top name and logo are the maintainer's trademarks.",
    ],
  },
}
