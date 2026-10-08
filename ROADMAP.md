# Roadmap

What Sensei Top is building, in the order it is building it, and what it
will not build. Dates are not promised: one maintainer works on this in
their spare time, and the order moves when players ask for something
louder than the plan expected. Vote and argue in
[Discussions](https://github.com/sensei-top/sensei-top/discussions).

The whole thing is free, now and later. There is no paid tier, no account
and no trial, and nothing you can unlock by paying. Wizards' Fan Content
Policy forbids charging for a project like this one, and this project
would not want to anyway. If it earns a place in your routine,
[donations](#donations) keep it maintained.

## Now: before the first release

- **Windows and Linux installers.** A desktop window around the tracker,
  a setup that finds Arena's and MTGO's logs for you, updates that apply
  themselves. The Windows build is signed through the Microsoft Store; the
  direct download is signed once the open-source signing programme
  answers.
- **The source goes public** under the AGPL-3.0, on GitHub, as a fresh
  one-commit snapshot. The history before it was written against the
  maintainer's own match data and is not published.
- **A translation layer**, so that every text in the app has a key before
  the first translation starts. English is the only language at launch.
- **A landing page**, one screen: what it shows, where to download it,
  what never leaves your machine, what is not planned, where to donate.
- **A version check**, once a day, against a static file this project
  hosts. It sends the version you run and nothing else, it is written on
  the page it reads from, and a switch in Settings turns it off.

## Next: the first releases after launch

In this order, unless Discussions says otherwise.

1. **Brazilian Portuguese.** The first translation, chosen because the
   maintainer is Brazilian and the first community asked is LigaMagic's.
2. **Sideboard help without a model.** Your own record for each matchup
   after boarding, read from Arena's own deck submissions; the cards in
   your 75 that answer what the opponent's deck does, as candidate ins; and
   a link to a published sideboard guide for the pairing, found through
   the Skill Issue Magic guide index, with credit to its author on every
   link. Nothing is generated and no "outs" are invented.
3. **Written guides with any model.** Today a written deck guide, match
   report or coach report comes from a prompt you copy into whatever
   assistant you already use, or from an Anthropic key you set yourself.
   Next: any provider that speaks the OpenAI format, and local models
   through Ollama or LM Studio, with the model named on every report it
   wrote.
4. **macOS, Arena only.** An unsigned build from GitHub's runners first;
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
- **Diagnostics bundle.** A file you make yourself when something breaks,
  redacted before it is written, that you attach to a bug report by hand.
  Nothing is ever sent on its own.

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
- **An account, telemetry or a paid tier.** No sign-up, no usage
  reporting, no subscription. The only requests the app makes on its own
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

Donations fund the maintainer's time. They buy nothing inside the app and
unlock no build, because the Fan Content Policy forbids requiring payment,
a subscription or a sign-up to reach fan content, and because an early
build for donors is exactly that. What a donation gets you: your name in
the credits if you want it there, a role on the Discord once it exists, a
vote on what comes next, and the option to sponsor one item on this
roadmap by name. The links are on the project page: Apoia.se for Brazil,
and one worldwide platform.
