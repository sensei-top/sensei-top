# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- A deck's **Guide** can now save its exported Markdown as a file: "Download
  .md" sits beside the copy button, as it does on the RCQ guide.

### Fixed

- On the MTGO picks page, a match no group takes because no saved list is
  in its format now names that format: "No saved list in Modern." rather
  than "No saved list fits."
- On Windows, `sensei-top config` no longer says it wrote the config file
  "(mode 600)": there `chmod` sets only the read-only flag.
- A deck's **Matchups** page keeps formats apart: a Magic Online deck
  with matches picked as different formats gets one row per format against
  each opponent, each naming its format, and a row opens that format's
  matches alone.

## [1.2.1] - 2026-10-21

### Changed

- The Windows app is on the
  [Microsoft Store](https://apps.microsoft.com/detail/9NZ5GQMCG1ZN), free.
  The Store version is signed, so Windows doesn't warn before installing
  it, and the Store keeps it up to date. The site and the install guide
  now offer it beside the installer, which is still unsigned.

### Fixed

- A Magic Online match that reveals Swords to Plowshares, Ancestral Recall
  or Fast // Furious can now be judged on that card's legality in the
  match's format. The card was matched to a copy with no legality on file.
- A Magic Online extra turn now counts toward the game's turns, and the
  cards played in it are on that turn instead of the one before.
- On **Live**, the strip's Game number no longer lags behind in a game 2
  or 3 hand, and while sideboarding its game and record agree with the
  plan card's result for the game just ended.
- In Portuguese, the dashboard's lists of cards, decks and colours read
  as Portuguese lists ("A, B e C") instead of being joined with English
  commas.

## [1.2.0] - 2026-10-21

### Added

- A Microsoft Store version of the Windows app. The Store keeps it up to
  date, and Settings says so. It starts when Windows starts only if you
  turn it on in Windows Settings → Apps → Startup, so Settings points
  there instead of showing the switch, and first run doesn't ask.
- Arena's log is found on its own on more Linux setups: Steam as a
  Flatpak or a Snap, Lutris, Heroic and Bottles (native or Flatpak), and
  plain Wine in `~/.wine` or `WINEPREFIX`, whatever the Wine user is
  called. When more than one prefix holds a log, the one Arena wrote to
  last is read, and `sensei-top doctor` lists the others.
- A `.tar.gz` of the Linux app beside the AppImage, for systems where the
  AppImage won't run. It never updates itself, and Settings doesn't offer
  to start it when you log in.

### Fixed

- A drawn game no longer counts as a loss in a deck's **Play vs draw**,
  nor toward the ten games a side needs before it shows a rate. The match
  report's play/draw record and `sensei-top report` count it the same way.
- A config file saved in an encoding other than UTF-8 no longer stops the
  app from answering. It is read as unreadable, with a warning in the
  log, as a file with a typo in it already was.
- The keep guide's ideal hand on **Live** could add up to eight cards for
  a deck with many lands and many creatures. It is always seven now.
- On a deck's **Guide**, your archetype's win rate in the field no longer
  counts Magic Online league lists, which are published only when they go
  5-0.
- A card with a cost like {2/W} counts 2 toward its mana value, as the
  rules say, instead of 1, in a deck's curve and the keep guide.

## [1.1.0] - 2026-10-19

### Added

- Game 1 and games 2–3, apart. **Matchups** has a column for each, a
  pairing's page two tiles of the same split, and the sideboard break's
  plan your own record in games 2–3 against the opponent's deck. Only
  best-of-three matches count, on Arena and Magic Online alike, and a
  drawn game counts in neither.

### Changed

- **Your library** on **Live** is now your decklist and nothing else:
  how many of each card are left, and the chance of drawing at least one
  in your next three draws, with your lands as the first row. The land,
  interaction and flood tiles above it are gone, and so is the footnote:
  the column's header says what the number is.
- **Live** says each thing once. **Match details** is gone from the bar
  under the page, since the strip at the top already shows the game, the
  turn and the opponent. The opponent's deck no longer repeats its name
  and confidence under the strip, and between games the strip names the
  opponent while the sideboard plan takes the page.
- A deck's page has a strip of three numbers under its name, on every
  tab: its matches, its games, and the gap between its win rates on the
  play and on the draw.
- The RCQ guide is a tab of its own on a deck's page, beside **Guide**.
  An old link to it still opens it.
- Every page writes numbers the same way: a whole percent ("58%") and a
  record as wins–losses ("6–3"). From five to nine matches a rate is
  shown muted, with "rough" beside the record; under five the record
  takes the rate's place, with a line saying it is too few for one.

### Fixed

- In English, some counts of one read as a plural, such as "1 cards
  seen" on **Live**. They now read "1 card seen".
- On Magic Online, a player who reconnects mid-game no longer splits
  that game in two, which also pushed every later game of the match one
  number up and lost who was on the play. Games that end on time, to
  inaction or in a draw are read as such, and a match lost on time is
  no longer left unfinished. A name with a space in it reads as one
  player, so that opponent's cards and results count. A match you only
  watched is left out without a warning. A game conceded in the middle
  of a mulligan is no longer counted as two.
- On Arena, an action you took back with undo, such as a spell you
  started to cast and cancelled, no longer counts as played. One
  message the app can't read no longer loses the rest of what arrived
  with it.
- **Live** no longer freezes for 15 seconds or more about once a minute
  during a game. Each time the app rebuilt your match history it held
  the database long enough to stop new log lines from being stored, and
  with a few hundred Magic Online games recorded that took most of the
  rebuild. Now the pause is under two seconds.
- Your recorded matches are read again once, the first time the app
  starts after the update, so these fixes reach the games you already
  played.

## [1.0.1] - 2026-10-17

### Fixed

- The installer's last page linked a GitHub Sponsors page that doesn't
  exist yet. It now links the site's **Donate** section, which lists
  every way to donate: Apoia.se for Brazil, and PayPal for everywhere
  else.
- Saving an MTGO match's deck and format while the app was rebuilding its
  match history could fail with "database is locked". It now waits for
  the rebuild to finish, up to a minute, and if the rebuild takes longer
  than that it says so in a sentence instead of showing an error.

## [1.0.0] - 2026-10-17

### Added

- Every card that gives you a prompt to copy now takes the answer back:
  the match report, the leak finder, the deck guide, the matchup briefs,
  the sideboard plan, matchup coverage, the Coach and the RCQ guide. Paste
  the assistant's whole answer into the box under the prompt and press
  **Save the answer**. The answer names the card it was written for, so
  one pasted into the wrong card is refused and nothing is stored. Before,
  only the deck guide, the briefs and the RCQ guide could be saved, and
  only from a terminal.
- A **Card data** card in **Settings**, under **Sources**: how many cards
  have rules text, and **Download card data** to fetch it or fetch it
  again.
- An optional **Folder of decks** for Magic Online, for the decks you
  export as `.dek` files. The app already read the decks Magic Online
  keeps beside its game logs.

### Changed

- The welcome steps ask which you play, Arena, Magic Online or both, and
  show only that client's setup.
- The Arena step draws where Detailed Logs are turned on in Arena, with
  **Check again**. **Home** keeps asking until Arena's log says they are
  on.
- Card data downloads on its own the first time the app opens, and
  **Ready** shows how far it has got. It is no longer a step of its own.
- The footer says where your match history is kept, instead of naming a
  database format.
- Written prose in the deck guide, the Coach and the RCQ guide fills the
  width of its card.

### Fixed

- Match times showed shifted by your offset from UTC, three hours early
  in Brazil. They now read in your own clock.
- After sideboarding, **Live**'s remaining library and keep guide counted
  game 1's list. They count the list you boarded into.
- **Live** showed no matchup brief when the deck's format was unknown,
  even with one already written. A written brief now shows first.
- Pick-Two Draft matches counted toward the Coach. They are Limited, and
  left out with the other draft queues.
- A match report could keep an earlier reading of the match after the
  app's read of its format changed.
- A Magic Online log line with a number in unusual digits, such as "²",
  is skipped with a warning instead of failing.
- **Home**'s field card could show the art of another deck of the same
  archetype. It now matches the deck it names.
- A card face Scryfall cannot find on its own, such as Enroot of
  Carnivorous Cultivator // Enroot, drew an empty box. It now takes the
  picture of the card it belongs to.

## [0.7.2] - 2026-10-13

The app is the same as 0.7.1's; this release carries the website.

### Added

- A help page on senseitop.com, in English and Brazilian Portuguese:
  installing, the first run, Magic Online, what to do when something looks
  wrong, and how to send a problem report.

### Changed

- The home page, rewritten in both languages around screenshots of the
  dashboard. They come from a copy of a real database with every player
  name and identifier replaced.
- A link to the site shared in a chat or a post shows a preview card.
- Visitors in Brazil land on the Portuguese help page, as they already did
  on the home and privacy pages.
- The bug report forms say the version is in Settings, under App.

## [0.7.1] - 2026-10-13

### Fixed

- The app's log no longer names a player. Magic Online warnings quoted
  handles and whole log lines; they now say which game, card and count.
  The diagnostics export masks the names an older log still holds, so a
  zip attached to a public issue carries none.
- The desktop window no longer downloads a spellcheck dictionary from
  Google on Windows and Linux, a request the privacy page never listed.
- The bug report forms say to leave "Include Player.log" unticked on a
  public issue.

## [0.7.0] - 2026-10-12

### Added

- The first public release: a desktop app for Windows 10 and 11 and for
  Linux that reads the logs Magic: The Gathering Arena and Magic Online
  already write and turns them into a dashboard on your own computer.
  Every match and game, turn by turn; your record with each deck and
  against each archetype; the real tournament metagame beside it. No
  account, no upload.
- **Home**: the last session, three things worth a look, and the win rate
  by week.
- **Live** (Arena): the match in progress, with a keep guide for the
  opening hand, a read of the opponent's likely hand, your remaining
  library and a sideboard plan between games. In ranked play it shows only
  what any tracker shows.
- **Matches**: every match, with a report and a turn-by-turn replay of
  each game, and a leak finder that reads for patterns across matches.
- **Decks**: each deck's record over every version, its matchups, and a
  guide that sets your list against the field.
- **Field**: the metagame from Magic Online and paper tournament results;
  TopDeck.gg's events too, through a free key of your own.
- **Coach**: a dated report across every deck, each one measured against
  the last.
- Written guides, reports and briefs as a prompt you paste into an
  assistant you already use, or through a Claude key you set yourself.
  Nothing is called without the key and a button press.
- Magic Online: its game logs read as they are written; the deck and
  format of each match picked by you, one at a time or hundreds at once.
- A first-run setup that finds Arena's log on its own, including Steam and
  Proton installs on Linux, asks where Magic Online keeps its logs, and
  downloads the card data.
- Updates that apply themselves from this project's releases on GitHub,
  checked once a day; a switch in Settings turns the check off.
- A verified backup of the database every day, and a restore button.
- A diagnostics export in Settings: a zip of the app's logs and a
  secret-free report, written only when you ask for it, for a bug report.
- The whole app in English and Brazilian Portuguese, chosen on first run
  or in Settings.
- On Windows, an installer in both languages, a system tray icon that
  keeps recording with the window closed, and start-with-Windows as an
  option. On Linux, an AppImage that updates itself in place.

[Unreleased]: https://github.com/sensei-top/sensei-top/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/sensei-top/sensei-top/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/sensei-top/sensei-top/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/sensei-top/sensei-top/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/sensei-top/sensei-top/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/sensei-top/sensei-top/compare/v0.7.2...v1.0.0
[0.7.2]: https://github.com/sensei-top/sensei-top/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/sensei-top/sensei-top/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/sensei-top/sensei-top/releases/tag/v0.7.0
