# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The app downloads card data again on its own once a day, and a few
  minutes after an Arena update that brings new cards, so a new set's
  cards get their rules text, and turn legal on release day, without a
  press of "Download again".
- The archetype definitions that name an opponent's deck are checked every
  hour while the app is open, not only when it starts, so a new set's
  decks get their names without restarting the app.

### Fixed

- Saving downloaded card data takes seconds instead of over ten minutes on
  a long match history, and no longer holds up the tracking of a game being
  played while it runs.

## [1.4.0] - 2026-11-09

### Added

- A free, optional account, in Settings under "Account": sign in with
  Google or Discord, in your browser. With it you can back up your match
  history to the cloud and bring it to another computer, where a match
  that computer has no log of shows on Matches as "Restored"; save
  everything in your account as one JSON file; and delete your cloud
  history or the whole account. The first sign-in asks about each use
  separately, with nothing chosen for you. Sensei Top works the same
  without an account. The account, error reports, Report a problem and
  "Help build the stats" are in the desktop app only, never in a run from
  source.
- Error reports, a separate yes on the account: when something goes wrong,
  the app sends a report to Sentry, with names, keys and file paths
  removed first.
- "Report a problem", in the tray, in Settings under "App", on an error
  message and on the screen shown when a page stops working: each press
  sends one report, with or without an account, and can attach the last
  500 lines of the app's own log. It asks before every report. You say
  whether it is a bug or an idea, and the report carries the page and the
  match you sent it from.
- "Help build the stats", a yes of its own that needs no account: it sends
  your games, with everything that names you or your opponent removed, to
  the private pool Sensei Top's own stats are built from. The last welcome
  step asks; an install already set up asks once, and Settings turns it on
  or off at any time.
- A page that stops working now says so, with Reload and "Report a
  problem", and the app keeps recording meanwhile.
- Decks has a search box for deck and card names, and decks with fewer
  than 5 matches fold into one group.
- A lost match's report links to the matchup, with your record in it, and
  a pairing shows what you brought in against it before.
- Settings restores the database from a dated list of backup copies, and
  "Restart now" relaunches the app.
- Guide and Coach show which stage they are at while they work.
- The header shows the card data's download while it runs.

### Changed

- The [privacy policy](https://senseitop.com/privacy/) and the
  [terms of use](https://senseitop.com/terms/) now describe the account,
  error reports, Report a problem and contributed games, dated 2026-11-05.
- The help pages on [senseitop.com](https://senseitop.com/help/) explain
  the account, "Help build the stats" and Report a problem.
- Settings is in six groups, each on a page of its own, and says "Saved"
  when a change is kept.
- A deck's pages open on a band with its art, and a match's page shows
  your own card.
- Pages load as outlines first, so nothing moves when the data arrives.
- Field opens on 15 days of tier B results, and Home's field card uses the
  same window.
- Signing in brings the app to the front and closes the browser tab.

## [1.3.0] - 2026-11-03

### Added

- A switch in Settings, "AI features", that hides everything AI writes:
  the coach, the written match reports and deck guides, the matchup briefs,
  and the prompts that write them. With it off, the app shows only what it
  reads from your games and from tournament results, and nothing already
  written is deleted. A new install asks on the Welcome screen; an install
  already set up keeps the features on.
- Terms of use on [senseitop.com](https://senseitop.com/terms/), in English
  and Brazilian Portuguese, linked from every page's footer.

### Changed

- The [privacy policy](https://senseitop.com/privacy/) is rewritten. It
  describes what the app does today, and in sections marked "Not available
  yet", the optional account, error reports, the rules coach and
  contributing games that are planned. None of those is in this release.
- The TopDeck.gg key moves from Settings' Writing section to Sources.
- The prompt cards no longer show a command-line import command; paste the
  answer in the dashboard instead.

### Removed

- The command-line paths that wrote with AI: `guide --prompt`, `--import`
  and `--author`, `rcq`, `brief`, and the coach's `config` flags. The
  dashboard does all of these. Every other command is unchanged.

## [1.2.4] - 2026-11-02

### Added

- Every release is announced in the repository's
  [Discussions](https://github.com/sensei-top/sensei-top/discussions/categories/announcements),
  under Announcements, with its notes, so following Discussions is enough
  to hear about a new version.
- Three pages on [senseitop.com](https://senseitop.com), in English and
  Brazilian Portuguese: how Sensei Top differs from Untapped, Sensei Top on
  Linux and the Steam Deck, and Sensei Top for Magic Online. The site now
  has a sitemap, and each page's title says what the app is.
- A new look for [senseitop.com](https://senseitop.com): the landing opens on
  a short demo of the app with captions, in English and Brazilian Portuguese,
  and now has a roadmap.

### Fixed

- The Microsoft Store package now carries Sensei Top's own tiles and Store logo
  instead of the build tool's placeholder.
- A player who uses only Arena no longer gets a warning about Magic Online
  in the app's log every time the tracker rebuilds its matches, when the
  settings file holds something else, such as a Claude key.
- The live status no longer says Magic Online's game logs are being watched
  while their folder can't be read, such as a folder that moved or a network
  share that dropped. It says so again once the folder can be read.
- An RCQ guide whose answer was copied for one list and saved after the
  list or its expected archetypes were edited is now marked on the RCQ page
  as written for another list. The prompt you copy says what it was built
  from, so the page can tell.
- Two rows in a deck's matchup coverage that share a name, because the
  tournament data files one name under two archetypes, now say which is
  which, as "Dimir Midrange · Bx Midrange".
- Reading a log again once its date format is known, or with a different
  `--locale`, no longer stores its entries a second time. An entry stored with
  no date takes its date instead.
- The keep guide's mulligan table and its mulligan cost line now count the same
  games: every version of the deck. The table used to count only the current
  list, so the two could disagree after an edit.
- The Live page no longer reads "1 untapped lands" for the opponent's mana.
- Win rates by game length no longer count a drawn or unfinished game against
  you, in `sensei-top report` and `/api/metrics/game-length`. The average length
  still counts every game.

## [1.2.3] - 2026-10-24

### Added

- The README and the site now say how Sensei Top is built: most of its
  code, tests and documentation are written by Claude, Anthropic's models,
  from the maintainer's plans. The README's "How it's built" section says
  what the maintainer does and how each change is reviewed and tested.
  Nothing in the app changes.

## [1.2.2] - 2026-10-23

### Added

- A deck's **Guide** can now save its exported Markdown as a file: "Download
  .md" sits beside the copy button, as it does on the RCQ guide.
- **Matches** now shows play against draw beside matches and games won:
  the gap between your game win rates on the play and on the draw, with
  both rates under it, as a deck's page already does.
- The **match report** explains itself: hover or focus a beat label (Race,
  Turned, Stranded and the rest) for one sentence on what it means. When
  you lost the race, the subhead names each lost game's biggest problem,
  or says no single cause stood out. A concession or a timeout says who
  ("You conceded"), and "Replay game N" opens the replay at the game's
  first flagged turn.
- A deck's **Matchups** view links to the **Field** for that deck's format.
- **Decks** can be filtered by format and sorted by last played, win rate
  or matches; every version keeps its tile.
- A deck's **Matchups** table has a "Who played first" switch: Game 1 and
  Post-board count only the games on the play, or on the draw. Games with
  no play/draw on record count under All only, and the table says how many.

### Changed

- **Decks** tells same-named decks apart: the one played most recently
  wears the "Newest" chip and the others show when they were played
  ("played Sep 3 to 14"). The version switcher marks its newest version,
  and Home's deck tiles mark same-named decks the same way.
- The **match report**'s top severity reads "Major" where it said
  "Decisive", which read like the game's result, and its Turned beat
  counts your own turns ("your turn 6"), as its findings do.
- The **match report**'s heading names the opponent as its Opponent row
  does, without the colour letters the pips beside it already show.
- A label that explains itself on hover or focus now shows an info icon
  beside it, everywhere in the dashboard.
- A deck's **Matchups** view shows the archetypes met ten times or more,
  and never fewer than the five most met; "Show all" opens the rest. Its
  Game 1 and Post-board headers explain themselves.
- **Field** keeps its controls in one row, and the most-played deck leads
  its tiles.
- **Home** draws a quiet placeholder where a deck has no card art, and
  each record names the window it covers.
- On **Live**, "Pick the deck" is a quieter button, and "Correct the deck"
  carries a pencil like the other edit buttons.
- **Home**'s three things no longer read as blank cards while they load:
  each shows its label and what it is waiting on, and the match and the
  field appear without waiting for the pattern.

### Fixed

- The **match report** says "your turn N" from Arena's own count of your
  turns, so a game whose log missed turns no longer reads too low (it said
  turn 2 where you were on turn 12), and a turn Arena never numbered is
  described without one. The leak finder's mana-screw check counts turns
  within each game, and a match with no numbered turn stays out of its
  rate instead of counting as clean.
- Every score reads the same way, your games first with an en dash: the
  match report's headline said "Lost 2-1" where the list said "Loss 1–2";
  both now say 1–2.
- A deck's page says "Post-board" where it said "Games 2–3", the Worst
  tile counts archetypes rather than showing a bare number, and the deck
  tiles say "win rate" beside the percentage. Live's lands strip reads
  "19 of 24 lands left in your library", under "Next draw".

- On the MTGO picks page, a match no group takes because no saved list is
  in its format now names that format: "No saved list in Modern." rather
  than "No saved list fits."
- On Windows, `sensei-top config` no longer says it wrote the config file
  "(mode 600)": there `chmod` sets only the read-only flag.
- A deck's **Matchups** page keeps formats apart: a Magic Online deck
  with matches picked as different formats gets one row per format against
  each opponent, each naming its format, and a row opens that format's
  matches alone.
- On Windows, a network folder (`\\server\share`) given for the database
  or the backups is now refused up front with a message, rather than
  failing partway through a backup, a restore or a check.

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

[Unreleased]: https://github.com/sensei-top/sensei-top/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/sensei-top/sensei-top/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/sensei-top/sensei-top/compare/v1.2.4...v1.3.0
[1.2.4]: https://github.com/sensei-top/sensei-top/compare/v1.2.3...v1.2.4
[1.2.3]: https://github.com/sensei-top/sensei-top/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/sensei-top/sensei-top/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/sensei-top/sensei-top/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/sensei-top/sensei-top/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/sensei-top/sensei-top/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/sensei-top/sensei-top/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/sensei-top/sensei-top/compare/v0.7.2...v1.0.0
[0.7.2]: https://github.com/sensei-top/sensei-top/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/sensei-top/sensei-top/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/sensei-top/sensei-top/releases/tag/v0.7.0
