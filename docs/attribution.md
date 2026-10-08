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
| [Scryfall](https://scryfall.com) | Card names, rules text, legality and each printing's Magic Online number, `mtgo_id` (the `default-cards` bulk file); card images and card art, one card at a time, each request naming the card | Scryfall's [API terms](https://scryfall.com/docs/api): no paywall in front of their data, no use of their name or logo that implies endorsement. For pictures: "Do not cover, crop, or clip off the copyright or artist name on card images", and no distorting, blurring or colour-shifting them; art shown alone must leave the artist and the source identifiable in the same interface. Their [rate limits](https://scryfall.com/docs/api/rate-limits) are 10 requests a second, 2 a second for a lookup by name, and 30 seconds of limited access after a refusal; `card_images.py` paces itself by them | `cards.py`, `card_images.py` |
| [MTGOFormatData](https://github.com/Badaro/MTGOFormatData) | The archetype definitions that name an opponent's deck. [Jiliac's fork](https://github.com/Jiliac/MTGOFormatData) is tried only when the first repository cannot be reached | Neither repository carries a licence file. The maintainer proposed MIT in the repository's own [issue 148](https://github.com/Badaro/MTGOFormatData/issues/148) and most contributors agreed there, but the file has not been added, and an agreement in an issue is not a licence | `archetypes/source.py` |
| [MTG_decklistcache](https://github.com/fbettega/MTG_decklistcache) | MTGO and Melee tournament results for the Field page. The Melee events originate on melee.gg, which this project never fetches; melee.gg's terms could not be read by a program on 2026-10-05 (HTTP 403) and are unread | GPL-3.0. Downloaded by each copy, never bundled or redistributed by this project | `metagame/source.py` |
| [TopDeck.gg](https://topdeck.gg) | Standings, records and decklists of completed events in the formats the user follows, through the user's own free key, once a day while the server runs (and on `sensei-top meta`). Player names and ids are used only to join rows in memory and never stored | TopDeck.gg's [API terms](https://topdeck.gg/docs/tournaments-v2), read in full on 2026-10-05 with the site's [Terms and Conditions](https://topdeck.gg/terms-and-conditions) (2022-03-01) and [Privacy Policy](https://topdeck.gg/privacy-policy) (2022-03-01). The API is "free to use, providing tournament data for your projects and applications"; "Any project using the API must include a visible credit and link back to TopDeck.gg"; "Most endpoints allow 100 requests per minute. Heavier endpoints like bulk tournament queries have lower limits", answered with a 429 and a `Retry-After` the fetch waits out. Nothing addresses a schedule or a sold product; the site's Terms reserve its own content "solely for your personal use", and the API page is the later, specific grant this project relies on. The Field page and each event page show the credit and the link beside the data. Decklists come back only "when tournament has ended OR organizer enabled "Show Decks"", and the fetch never asks for the staff view | `metagame/topdeck.py` |
| [mtgo.com](https://www.mtgo.com/decklists) | The public result pages of events in the formats the user follows (Standard and Modern unless changed): the decklist index, then each event's page for its decklists, standings and bracket. A league's page is read again while its date is today or yesterday, because its lists are added through the day; a challenge's page is read once. A month's archive page is read only when the previous successful fetch, or the start of the format window, falls in an earlier calendar month than today — normally one page, the previous month, the first time the app runs after a month boundary, and none otherwise. Player handles and login ids are dropped at parse time and never stored | Read in full on 2026-10-05: Daybreak's [Terms of Service](https://www.daybreakgames.com/terms-of-service) (last updated 2026-07-13), the [MTGO EULA](https://www.mtgo.com/eula) (updated 2022-05-31), the [API Policy](https://census.daybreakgames.com/) on the Census page (undated) and the [Legal Notices](https://www.daybreakgames.com/legal) (2026-08-24). mtgo.com has no terms of its own: its footer links Daybreak's, and Daybreak's [list of websites](https://www.daybreakgames.com/websites) names it, which is what makes the Terms apply. Neither host has a `robots.txt`. The Terms bind anyone "accessing and/or using" the site (§1); the EULA binds MTGO account holders only. Nothing addresses a program reading the site: §7.1's "scrape" sits in a list of malware ("virus, corrupted data, trojan horse, bot, keystroke logger ..."), so it is ambiguous, not a rule; load is addressed only in general words — §7.1 "Interfere with, degrade, harm or disrupt the operation of any Daybreak Game(s)", EULA §12.1(d) "an unreasonable or disproportionately large load" — which one request a second, and a few dozen requests a day per copy for the default formats — about three times that when all seven are followed — does not approach. Commercial use is the live question. §7.1 and §13(f) forbid using any part of a Daybreak website "for commercial purposes, except as expressly permitted herein", and the express permission is §14.3, for fan sites and apps that "share ... information about any Daybreak Game(s)": they may earn from advertising, "premium functionality and content" and paid downloads, but "If you intend to charge a subscription or access fee ... you first must execute a Fansite license agreement". Nothing is sold and no fee is charged (donations only, decided 2026-10-07), so that agreement is not needed; a donation is neither a subscription nor an access fee. §14.3 also grants "Permission to link from the Fansite to the associated Daybreak Website"; §14.4 forbids Daybreak's or the game's name in the app's name and anything that suggests sponsorship or endorsement, both honoured. Hosting this data for others (plan 9's snapshot) is "make available ... for any commercial purposes" (§7.1) and "distribute" (§13(a)) with no express permission — §14.3 covers only game data "acquired via Daybreak's API" — so it waits for Daybreak's written consent. The Census API's listed MTGO collections hold no decklists (checked 2026-10-05), so it is not the route today. A request from Daybreak to remove a stored event is answered as "Rules for a new source" says | `metagame/mtgo_site.py` |
| [Anthropic](https://www.anthropic.com) | The Claude API, only when the user configures a key and presses a generate button | The user's own account and key, under Anthropic's terms | `llm/client.py` |

Sensei Top is not produced by, endorsed by or affiliated with Scryfall,
TopDeck.gg, Daybreak Games and mtgo.com, melee.gg, Anthropic, or the
maintainers of MTGOFormatData and MTG_decklistcache. Their names appear here
to credit their work.

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
5. A source that asks for its data to be removed is answered by the next
   release: the data is deleted and kept out of later refreshes. None of the
   terms read asks for this. It is the project's own rule, because a request
   is the one way a source can say that a page was emptied on purpose —
   otherwise an event's decklists are kept after the source's copy comes
   back empty (`docs/metagame.md`, "When a source empties an event").
