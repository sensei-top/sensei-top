# Attribution

Read this when adding, changing or removing anything Sensei Top downloads, or
when writing text that names a third party. It lists every outside source
this application uses, what it takes from each, and on what terms.

Sensei Top bundles none of the data below. Each installed copy downloads what
it needs to the user's own machine.
Nothing about a user's games is sent to any of these sources, with two
exceptions. A request for a card's picture names that card, so Scryfall
can see which cards a copy has shown, never when, against whom or with
what result. The other is the opt-in call `docs/llm.md` describes.

## Wizards of the Coast

Sensei Top is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.

The sentence above is Wizards' own wording and is kept on one line so it
can be compared with the
[policy page](https://company.wizards.com/en/legal/fancontentpolicy). Only
the title is ours.

Sensei Top reads the log files Magic: The Gathering Arena and Magic Online
write on the user's own machine, and the card database an installed Arena
client ships. It changes neither client and reads nothing from their
memory.

## Sources

| Source | What Sensei Top takes | Terms | Fetched by |
|---|---|---|---|
| [Scryfall](https://scryfall.com) | Card names, rules text and legality (the `default-cards` bulk file); card images and card art, one card at a time, each request naming the card | Scryfall's [API terms](https://scryfall.com/docs/api): no paywall in front of their data, no use of their name or logo that implies endorsement. For pictures: "Do not cover, crop, or clip off the copyright or artist name on card images", and no distorting, blurring or colour-shifting them; art shown alone must leave the artist and the source identifiable in the same interface. Their [rate limits](https://scryfall.com/docs/api/rate-limits) are 10 requests a second, 2 a second for a lookup by name, and 30 seconds of limited access after a refusal; `card_images.py` paces itself by them | `cards.py`, `card_images.py` |
| [MTGOFormatData](https://github.com/Badaro/MTGOFormatData) | The archetype definitions that name an opponent's deck. [Jiliac's fork](https://github.com/Jiliac/MTGOFormatData) is tried only when the first repository cannot be reached | Neither repository carries a licence file. The maintainer proposed MIT in the repository's own [issue 148](https://github.com/Badaro/MTGOFormatData/issues/148) and most contributors agreed there, but the file has not been added, and an agreement in an issue is not a licence | `archetypes/source.py` |
| [MTG_decklistcache](https://github.com/fbettega/MTG_decklistcache) | MTGO and Melee tournament results for the Field page | GPL-3.0. Downloaded by each copy, never bundled or redistributed by this project | `metagame/source.py` |
| [TopDeck.gg](https://topdeck.gg) | Tournament results, through their API and the user's own free key | TopDeck.gg's [API terms](https://topdeck.gg/docs/tournaments-v2): "Any project using the API must include a visible credit and link back to TopDeck.gg." The Field page shows both beside the data | `metagame/topdeck.py` |
| [Anthropic](https://www.anthropic.com) | The Claude API, only when the user configures a key and presses a generate button | The user's own account and key, under Anthropic's terms | `llm/client.py` |

Sensei Top is not produced by, endorsed by or affiliated with Scryfall,
TopDeck.gg, Anthropic, or the maintainers of MTGOFormatData and
MTG_decklistcache. Their names appear here to credit their work.

## Fonts and symbols

These ship inside the dashboard's build. The credits view in the dashboard
shows this same list, each work with its copyright notice, and links to
the licence. The build does not carry the licence text itself yet
(`docs/status.md`, "Code health").

| Work | Used for | Licence |
|---|---|---|
| [Mana](https://github.com/andrewgioia/mana) by Andrew Gioia | The mana symbol glyphs, inlined in `components/ui/ManaPips.tsx` | Glyphs under [SIL OFL 1.1](https://openfontlicense.org). Mana symbol imagery © Wizards of the Coast |
| [Bricolage Grotesque](https://github.com/ateliertriay/bricolage) | Headings and headline numbers | SIL OFL 1.1. Copyright 2022 The Bricolage Grotesque Project Authors (https://github.com/ateliertriay/bricolage) |
| [Hanken Grotesk](https://github.com/marcologous/hanken-grotesk) | Interface text and numbers | SIL OFL 1.1. Copyright 2021 The Hanken Grotesk Project Authors (https://github.com/marcologous/hanken-grotesk) |

## Rules for a new source

1. It meets the standard for free downloads in `docs/llm.md`: reference
   lookups only, fail-soft always, no more than the feature needs.
2. It has terms that allow this use, and they are linked in the table
   above. A source with no licence is asked first, and the answer is
   recorded here. MTGOFormatData was added before this rule was written,
   and its licence is still pending (`docs/status.md`, "Waiting on a
   third party").
3. It gets a row in this table, and an entry in the dashboard's credits
   (`web/src/credits.ts`), in the same change that adds the fetch.
4. Where its terms ask for a visible credit, the dashboard shows one beside
   the data, not only on this page.
