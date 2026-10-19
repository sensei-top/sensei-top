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
free download, listed free when it goes up and priced later, for anyone who
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
English. What comes first after it:

1. **Game 1 and games 2 and 3, apart.** Your record in each matchup split
   into the first game and the games after sideboarding, for best-of-three
   matches, from Arena and Magic Online alike: on a deck's Matchups, on
   each pairing, and, for Arena, between games on Live.
2. **Fixes to how Magic Online's log is read.** Games that end on time,
   to inaction or in a draw are read as such, and a match lost on time
   is no longer left unfinished. A player who reconnects no longer opens
   a phantom game that pushed every later game of the match one number
   up. A name with a space in it reads as one player, and a match you
   only watched is left out without a warning. Each fix also mends
   every match you already recorded.
3. **Finding Arena on more Linux setups.** Every Steam library, Flatpak
   and Snap Steam, Lutris, Bottles and Heroic, and the newest log when
   more than one is found.

Outside this order, because it waits on Microsoft rather than on the
work: **the Microsoft Store build** of the same app, which the Store
signs. It is listed free at first and priced once Microsoft confirms an
individual developer may sell and the other blockers `docs/status.md`
names clear. The direct download stays unsigned for
now: the open-source signing programme asks for more public use first.

## Next

In this order, unless Discussions says otherwise.

1. **Seeing that the tracker is reading.** A page that says where your
   log is, when it was last read, how many matches came from it, and
   whether Arena's Detailed Logs setting is off, with the exact place to
   turn it on; a warning when a match looks missing; and what changed in
   each release, dated, inside the app.
2. **Your data out, and every column explained.** Your matches and games
   as a CSV file; a one-line definition on every table column; and a tour
   of the dashboard in the help pages, in both languages, which says what
   the tracker reads and that it sends nothing.
3. **Sideboard help without a model.** The cards in your 75 that answer
   what the opponent's deck does, as candidate ins, and a link to a
   published sideboard guide for the pairing, found through the Skill
   Issue Magic guide index, with credit to its author on every link.
   Nothing is generated and no "outs" are invented.
4. **Win rates per card**, from your own games: with the card in your
   opening hand, drawn, and cast, with the number of games beside each
   rate.

## Later

- **Written guides with any model.** Today a written deck guide, match
  report or coach report comes from a prompt you copy into whatever
  assistant you already use, or from an Anthropic key you set yourself.
  Later: any provider that speaks the OpenAI format, and local models
  through Ollama or LM Studio, with the model named on every report it
  wrote.
- **macOS, Arena only.** An unsigned build from GitHub's runners first;
  notarization when donations cover Apple's fee.
- **MTGO on the Live page**: the opponent's revealed cards during a game
  and the between-games plan, read from MTGO's game log the way Arena's
  Live page reads Arena's.
- **Caution cards**: the cards to watch for from the deck your opponent
  most likely plays, with their rules text.
- **Finding your history faster**: date ranges, a search, your matches
  grouped by day, and league runs with their trophies.
- **Historic, Explorer and Timeless**, the Arena-only formats other than
  Alchemy and Brawl, with the field data and format features the MTGO
  formats have.
- **An optional paid tier**, once a few thousand players use the tracker
  regularly. A subscription for deeper features, with a monthly allowance
  of written reports inside it, so you never set up a key or paste a
  prompt. It is gated by feature, never by your rank or the events you
  play. It is the only thing that asks for an account, made when you
  subscribe: a code sent to your email, or Google, Discord or X. The free
  tracker, the copy prompt and your own key stay as they are.
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
  [docs/status.md](docs/status.md), which is the project's own backlog.

## Donations

Donations fund the maintainer's time. They unlock nothing inside the app
and no early build; that is what the paid tier is for, and a donation is
not a payment for it. What a donation gets you: your name in
the credits if you want it there, a vote on what comes next, and the
option to sponsor one item on this roadmap by name. The links are on the
project page: [Apoia.se](https://apoia.se/senseitop) for Brazil, and one
worldwide platform.
