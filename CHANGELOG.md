# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/sensei-top/sensei-top/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/sensei-top/sensei-top/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/sensei-top/sensei-top/releases/tag/v0.7.0
