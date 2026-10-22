# Roadmap

What Sensei Top is building, in the order it is building it, and what it
will not build. Dates are not promised: one maintainer works on this in
their spare time, and the order moves when players ask for something
louder than the plan expected. Vote and argue in
[Discussions](https://github.com/sensei-top/sensei-top/discussions).

The tracker is free and needs no account, now and later: your match
history, your record in every matchup, the leak finder, the turn-by-turn
replay, and written guides through a prompt you paste into any assistant
or through a key of your own. Two paid things are planned, and neither
takes any of that away. The Microsoft Store build is the same app as the
free download, [listed free](https://apps.microsoft.com/detail/9NZ5GQMCG1ZN) since 2026-10-21 and priced later, for anyone who
would rather support the project that way. Later, an [optional paid tier](#later) adds deeper
features and a monthly allowance of written reports, and it is the only
thing that asks for an account. If the tracker earns a place in your
routine, [donations](#donations) keep it maintained.

What it is for: one tracker for both Arena and Magic Online, on Windows
and Linux (the Steam Deck included), that shares none of your matches
with anyone and shows how many games stand behind every rate it gives you.
The order below follows from that.

## Now

1.0.0 shipped on 2026-10-17, with the Windows installer, the Linux
AppImage, updates that apply themselves, and Brazilian Portuguese beside
English. Since then: games 1 and 2–3 apart in every matchup, fixes to how
Magic Online's log is read, and Arena found on more Linux setups
([CHANGELOG.md](CHANGELOG.md)). What comes before the next release:

1. **The Microsoft Store build** of the same app, which the Store signs,
   [listed free](https://apps.microsoft.com/detail/9NZ5GQMCG1ZN) since 2026-10-21. It is priced once Microsoft
   confirms an individual developer may sell and the other blockers clear. The direct
   download stays unsigned for now: the open-source signing programme
   asks for more public use first. (BL-070, BL-072)
2. **One product, not a row of features.** A pass over every page for
   what a player wants to know and in what order, so the dashboard
   reads as one app rather than features set side by side. (BL-088)

## Next

In this order, unless Discussions says otherwise.

1. **Seeing that the tracker is reading.** A page that says where your
   log is, when it was last read, how many matches came from it, and
   whether Arena's Detailed Logs setting is off, with the exact place to
   turn it on; a warning when a match looks missing; and what changed in
   each release, dated, inside the app. (BL-001)
2. **Your data out, and every column explained.** Your matches and games
   as a CSV file; a one-line definition on every table column; and a tour
   of the dashboard in the help pages, in both languages, which says what
   the tracker reads and that it sends nothing. (BL-002, BL-003)
3. **Sideboard help without a model.** The cards in your 75 that answer
   what the opponent's deck does, as candidate ins, and a link to a
   published sideboard guide for the pairing, found through the Skill
   Issue Magic guide index, with credit to its author on every link.
   Nothing is generated and no "outs" are invented. (BL-005)
4. **Win rates per card**, from your own games: with the card in your
   opening hand, drawn, and cast, with the number of games beside each
   rate. (BL-004)
5. **The known bugs.** Everything [BACKLOG.md](BACKLOG.md) lists as a
   bug: labels that read alike for two different archetypes, mulligan
   numbers counted two ways, a field with no paper results after
   2026-08-16, an RCQ answer saved against an edited list, and a warning
   on every rebuild for players without Magic Online first (BL-029,
   BL-032, BL-033, BL-043, BL-056); then the rest (BL-025, BL-026,
   BL-027, BL-028, BL-030, BL-031, BL-034, BL-035, BL-036, BL-037,
   BL-040, BL-041, BL-042, BL-047, BL-048, BL-050, BL-051, BL-053,
   BL-054, BL-080, BL-081, BL-086, BL-087).

## Later

- **Written guides with any model.** Today a written deck guide, match
  report or coach report comes from a prompt you copy into whatever
  assistant you already use, or from an Anthropic key you set yourself.
  Later: any provider that speaks the OpenAI format, and local models
  through Ollama or LM Studio, with the model named on every report it
  wrote. (BL-007)
- **macOS, Arena only.** An unsigned build from GitHub's runners first;
  notarization when donations cover Apple's fee. (BL-009)
- **MTGO on the Live page**: the opponent's revealed cards during a game
  and the between-games plan, read from MTGO's game log the way Arena's
  Live page reads Arena's. (BL-013)
- **Caution cards**: the cards to watch for from the deck your opponent
  most likely plays, with their rules text. (BL-020)
- **Finding your history faster**: date ranges, a search, your matches
  grouped by day, and league runs with their trophies. (BL-021)
- **Historic, Explorer and Timeless**, the Arena-only formats other than
  Alchemy and Brawl, with the field data and format features the MTGO
  formats have. (BL-012)
- **An optional paid tier**, once a few thousand players use the tracker
  regularly. A subscription for deeper features, with a monthly allowance
  of written reports inside it, so you never set up a key or paste a
  prompt. It is gated by feature, never by your rank or the events you
  play. It is the only thing that asks for an account, made when you
  subscribe: a code sent to your email, or Google, Discord or X. The free
  tracker, the copy prompt and your own key stay as they are. (BL-006)
- **A Discord server**, once there are enough people to staff one.
  Discussions on GitHub come first.

## Never

These are decisions, not gaps. Each one was considered and refused.

- **An overlay or any window over the game.** The Live page is a page in
  the tracker's own window.
- **Live advice during an event.** In an Arena event (paid events,
  drafts, the Arena Open, Directs, Qualifiers, a Direct Challenge) the Live
  page shows what any tracker shows: your library, draw odds, the cards
  your opponent has revealed and what deck they point to. Keep advice, hand
  reads and play-arounds appear in casual games, on the ranked ladder and
  between games, and a switch in Settings hides them everywhere. Until
  October 2026 the ladder got none either. The rules that could reach a
  tracker are the
  [Digital Tournament Rules](https://blogs.magicjudges.org/rules/dtr/) and
  the [Digital Infraction Procedure Guide](https://blogs.magicjudges.org/rules/dipg/2-2/):
  they allow deck tracking software that shows no private information,
  they count play advice from an outside source as outside assistance, and
  they govern tournaments, which the ladder is not. On the ladder only
  [Wizards' Terms](https://company.wizards.com/en/legal/terms) apply, and
  they treat every tracker alike. The terms of the
  [Arena Open](https://magic.wizards.com/en/news/mtg-arena/arena-open-terms-and-conditions)
  and [Arena Direct](https://magic.wizards.com/en/news/mtg-arena/arena-direct-terms-and-conditions)
  say nothing of trackers either way, so events keep the stricter line.
- **Reading the memory of, injecting into or automating either client.**
  The tracker reads the log files Arena and MTGO already write, with
  Arena's own Detailed Logs setting on, and nothing else.
- **Collecting or sharing your matches.** Not by default, and not as an
  opt-in: your match history is never contributed to us or to a shared
  dataset. The one thing that leaves your computer is a report you ask to
  generate with your own key, which sends that match to the model you
  configured. The matchup numbers from outside your own games come from
  published tournament results.
- **Draft.** The draft assistant was removed in October 2026 and is not
  coming back in this project.
- **Mobile.** iOS makes log reading impossible and Android impractical.
- **Telemetry, or an account for anything free.** No usage reporting,
  and nothing free ever asks you to sign up. The only requests the app
  makes on its own
  are reference downloads (card data, images, archetype definitions,
  tournament results) and a daily version check, which a switch in
  Settings turns off.
- **Alchemy and Brawl.** Games in them still appear in your history, but
  no field data or format-specific feature is built for them.

## Where it comes from

- **Installers come only from the
  [GitHub releases](https://github.com/sensei-top/sensei-top/releases)**,
  which [senseitop.com](https://senseitop.com) links to, and later from
  the Microsoft Store listing. Any other download site is not this
  project's.
- **The app never contacts senseitop.com.** Updates and the version check
  come from the GitHub releases, and the tracker runs on your computer
  with no server of this project's behind it. If the site went away, the
  tracker would keep working.
- **The source is on GitHub under the AGPL-3.0**, developed in the open
  since 1.0.0, so anyone can build it, and fork it if the project ever
  stops.

## How fixes ship

- **A log change is fixed first.** Arena and MTGO change their logs
  without notice. A report that includes the lines that broke, with names
  removed, goes to the front of the queue, and the fix reaches every match
  you already recorded, because raw log events are stored verbatim and
  everything else is rebuilt from them.
- **Only the latest release receives fixes.** Updates apply themselves,
  and there is no long-term branch.
- **A fix for a security promise** ([SECURITY.md](SECURITY.md)) ships on
  its own, outside the normal cadence.
- Everything known to be wrong or missing is listed in
  [BACKLOG.md](BACKLOG.md), each item with an ID this page cites.

## Donations

Donations fund the maintainer's time. They unlock nothing inside the app
and no early build; that is what the paid tier is for, and a donation is
not a payment for it. What a donation gets you: your name in
the credits if you want it there, a vote on what comes next, and the
option to sponsor one item on this roadmap by name. The links are on the
project page: [Apoia.se](https://apoia.se/senseitop) for Brazil, and one
worldwide platform.
