# Roadmap

What Sensei Top is building, in the order it is building it. What it will
not build, and why, is in [docs/status.md](docs/status.md#not-planned).
Dates are not promised: one maintainer works on this in their spare time,
and the order moves when players ask for something louder than the plan
expected. Vote and argue in
[Discussions](https://github.com/sensei-top/sensei-top/discussions).

The tracker is free and works fully without an account, now and later:
your match history, your record in every matchup, the leak finder, the
turn-by-turn replay, and written guides through a prompt you paste into
any assistant or through a key of your own. A free, optional account
adds a backup of your match history and error reports you choose to send,
and [next](#next) a rules coach that answers with the rule numbers it
relied on. Two paid things are planned, and neither takes any of that
away. The Microsoft Store build is the same app as the free download,
[listed free](https://apps.microsoft.com/detail/9NZ5GQMCG1ZN) since
2026-10-21 and priced later, for anyone who would rather support the
project that way. Later, an [optional paid tier](#later) adds deeper
features and a monthly allowance of written reports. Both are
[on hold](#on-hold) until more players use the tracker, and nothing is
sold before then. If the tracker earns a place in your routine,
[donations](#donations) keep it maintained.

What it is for: one tracker for both Arena and Magic Online, on Windows
and Linux (the Steam Deck included), that shares none of your matches
with anyone, backs them up only if you ask, and shows how many games stand
behind every rate it gives you.
The order below follows from that.

## Now

1.0.0 shipped on 2026-10-17, with the Windows installer, the Linux
AppImage, updates that apply themselves, and Brazilian Portuguese beside
English. Since then: games 1 and 2–3 apart in every matchup, fixes to how
Magic Online's log is read, Arena found on more Linux setups, and in 1.4.0
a free, optional account. Sign in with Google or Discord, or never: it
backs up your match history and sends error reports, each only if you
turn it on, on one screen where nothing is ticked for you
([CHANGELOG.md](CHANGELOG.md)). What comes before the next release:

1. **The Microsoft Store build** of the same app, which the Store signs,
   [listed free](https://apps.microsoft.com/detail/9NZ5GQMCG1ZN) since 2026-10-21. Its price is
   [on hold](#on-hold). The direct
   download stays unsigned for now: the open-source signing programme
   asks for more public use first. (BL-070, BL-072)

## Next

In this order, unless Discussions says otherwise.

1. **A rules coach**, for players signed in to the free account. It
   answers rules and card questions in English, on the website and in
   the app, and cites the rule numbers it used. It is a hosted AI
   model, so each answer says it may be wrong and to ask a judge at a
   tournament, and there is a daily limit per player. The coach is never
   sent your matches. An "AI features" switch in Settings hides the
   coach and the written guides. (BL-101, BL-102)
2. **An overlay for Arena.** The Live page's reads in a window of the
   tracker's own, on top of the game, under the rule below for events. It
   draws over Arena and never injects into it. Magic Online does not get
   one. (BL-098)
3. **Sideboard guides, with no generated answers.** The cards in your 75
   that answer what the opponent's deck does, as candidate ins, and a link
   to a published sideboard guide for the pairing, found through the Skill
   Issue Magic guide index, with credit to its author on every link.
   Nothing is generated and no "outs" are invented. (BL-005)
4. **Win rates per card**, from your own games: with the card in your
   opening hand, drawn, and cast, with the number of games beside each
   rate. (BL-004)
5. **Your data out, and every column explained.** Your matches and games
   as a CSV file; a one-line definition on every table column; and a tour
   of the dashboard in the help pages, in both languages, which says what
   the tracker reads and that it sends nothing. (BL-002, BL-003)
6. **MTGO on the Live page**: the opponent's revealed cards during a game
   and the between-games plan, read from MTGO's game log the way Arena's
   Live page reads Arena's. (BL-013)
7. **The known bugs.** Everything [BACKLOG.md](BACKLOG.md) lists as a
   bug: a field with no paper results after 2026-08-16 first (BL-032);
   then the rest (BL-025, BL-026,
   BL-027, BL-028, BL-030, BL-031, BL-034, BL-035, BL-037,
   BL-040, BL-042, BL-047, BL-048, BL-050, BL-051,
   BL-080, BL-087, BL-097).

## Later

- **Seeing that the tracker is reading.** A page that says where your
  log is, when it was last read, how many matches came from it, and
  whether Arena's Detailed Logs setting is off, with the exact place to
  turn it on; a warning when a match looks missing; and what changed in
  each release, dated, inside the app. (BL-001)
- **Written guides with any model.** Today a written deck guide, match
  report or coach report comes from a prompt you copy into whatever
  assistant you already use, or from an Anthropic key you set yourself.
  Later: any provider that speaks the OpenAI format, and local models
  through Ollama or LM Studio, with the model named on every report it
  wrote. (BL-007)
- **macOS, Arena only.** An unsigned build from GitHub's runners first;
  notarization when donations cover Apple's fee. (BL-009)
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
  tracker, the copy prompt and your own key stay as they are. Preparing
  it is [on hold](#on-hold). (BL-006)
- **A Discord server**, once there are enough people to staff one.
  Discussions on GitHub come first.

## On hold

Since 2026-11-09, everything that only prepares selling waits: the Store
listing's price, the paid tier, and the questions to Microsoft, Daybreak
and TopDeck.gg that only a sale raises (BL-070, BL-006, BL-077, BL-078).
The tracker is too small today for either paid thing to pay for the work
it takes, so that work goes to what brings players instead. It is taken
up again when about 100 installs a day check for updates or 1,000 players
use the tracker in a month, whichever comes first, and the decision is
looked at again on 2027-03-01. Below that, it stays on hold through 2027.

## Where it comes from

- **Installers come only from the
  [GitHub releases](https://github.com/sensei-top/sensei-top/releases)**,
  which [senseitop.com](https://senseitop.com) links to, and later from
  the Microsoft Store listing. Any other download site is not this
  project's.
- **The tracker never needs senseitop.com.** Updates and the version
  check come from the GitHub releases, and the tracker runs on your
  computer. Once they ship, the account and the rules coach are the only
  parts that talk to a server of this project's, and only when you use
  them. If the site went away, the tracker would keep working.
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
