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
takes any of that away. At release, the Microsoft Store build is the
same app as the free download, sold for anyone who would rather support
the project that way. Later, an [optional paid tier](#later) adds deeper
features and a monthly allowance of written reports, and it is the only
thing that asks for an account. If the tracker earns a place in your
routine, [donations](#donations) keep it maintained.

## Now: before the first release

- **Windows and Linux installers.** A desktop window around the tracker,
  a setup that finds Arena's log and asks where MTGO keeps its own, updates
  that apply themselves. On Windows, a free installer and a paid
  Microsoft Store build of the same app; the Store signs its build, and
  the direct download is signed once the open-source signing programme
  answers. On Linux, an AppImage, with
  steps in `INSTALL.md` for Arch-based distributions, Ubuntu and SteamOS's
  desktop mode, tried on a Steam Deck before the release. No Flatpak, AUR
  or `.deb` package.
- **The source goes public** under the AGPL-3.0, on GitHub, as a fresh
  one-commit snapshot. The history before it was written against the
  maintainer's own match data and is not published.
- **Brazilian Portuguese**, alongside English: the first testers are
  Brazilian, and the first community asked is LigaMagic's. Every text in
  the app already has a key, so the next language is a catalogue, not a
  rewrite. Card, deck and archetype names stay in English.
- **A landing page**, one screen: what it shows, where to download it,
  what never leaves your machine, what is not planned, where to donate.
- **A version check**, once a day, against this project's releases on
  GitHub. It sends nothing about your games, it is written in `INSTALL.md`
  and on the first setup page, and a switch in Settings turns it off.
- **A diagnostics bundle.** A file you make yourself when something breaks,
  redacted before it is written, that you attach to a bug report by hand.
  Nothing is ever sent on its own.

## Next: the first releases after launch

In this order, unless Discussions says otherwise.

1. **Sideboard help without a model.** Your own record for each matchup
   after boarding, read from Arena's own deck submissions; the cards in
   your 75 that answer what the opponent's deck does, as candidate ins; and
   a link to a published sideboard guide for the pairing, found through
   the Skill Issue Magic guide index, with credit to its author on every
   link. Nothing is generated and no "outs" are invented.
2. **Written guides with any model.** Today a written deck guide, match
   report or coach report comes from a prompt you copy into whatever
   assistant you already use, or from an Anthropic key you set yourself.
   Next: any provider that speaks the OpenAI format, and local models
   through Ollama or LM Studio, with the model named on every report it
   wrote.
3. **macOS, Arena only.** An unsigned build from GitHub's runners first;
   notarization when donations cover Apple's fee.

## Later

- **MTGO on the Live page**: the opponent's revealed cards during a game
  and the between-games plan, read from MTGO's game log the way Arena's
  Live page reads Arena's.
- **A Discord server**, once there are enough people to staff one.
  Discussions on GitHub come first.
- **Opt-in match contributions.** A way to send your finished matches,
  with the exact payload shown before anything leaves, to build matchup
  numbers from real games. Not built until real usage shows it is worth
  the trust it asks for, and never on by default.
- **An optional paid tier**, once a few thousand players use the tracker
  regularly. A subscription for deeper features, with a monthly allowance
  of written reports inside it, so you never set up a key or paste a
  prompt. It is gated by feature, never by your rank or the events you
  play. It is the only thing that asks for an account, made when you
  subscribe: a code sent to your email, or Google, Discord or X. The free
  tracker, the copy prompt and your own key stay as they are.

## Never

These are decisions, not gaps. Each one was considered and refused.

- **An overlay or any window over the game.** The Live page is a page in
  the tracker's own window.
- **Live advice during a ranked game.** In ranked or competitive play the
  Live page shows what any tracker shows: your library, draw odds, the
  cards your opponent has revealed and what deck they point to. Keep
  advice, hand reads and play-arounds appear only in unranked games and
  between games.
- **Reading the memory of, injecting into or automating either client.**
  The tracker reads the log files Arena and MTGO already write, with
  Arena's own Detailed Logs setting on, and nothing else.
- **Draft.** The draft assistant was removed in October 2026 and is not
  coming back in this project.
- **Mobile.** iOS makes log reading impossible and Android impractical.
- **Telemetry, or an account for anything free.** No usage reporting,
  and nothing free ever asks you to sign up. The only requests the app
  makes on its own
  are reference downloads (card data, images, archetype definitions,
  tournament results) and the daily version check above.
- **Arena-only formats** (Historic, Explorer, Timeless, Alchemy, Brawl).
  Games in them still appear in your history, but no field data or
  format-specific feature is built for them.

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
