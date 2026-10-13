<p align="center">
  <img src="web/public/favicon.svg" width="96" height="96" alt="">
</p>

<h1 align="center">Sensei Top</h1>

<p align="center">
  Free, fully local match analytics for Magic: The Gathering Arena and Magic Online.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-AGPL--3.0-blue" alt="Licence: AGPL-3.0"></a>
  <a href="https://github.com/sensei-top/sensei-top/releases"><img src="https://img.shields.io/github/v/release/sensei-top/sensei-top" alt="Latest release"></a>
  <a href="https://github.com/sensei-top/sensei-top/actions/workflows/ci.yml"><img src="https://github.com/sensei-top/sensei-top/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

<p align="center">
  <img src="docs/images/home.png" alt="The Home page: the last session's record, the last thirty days' record, and three cards: the last match, one pattern across your matches, and the field you are playing in.">
</p>

Sensei Top reads the logs Arena and Magic Online already write on your
computer and turns them into a dashboard: every match and game, turn by
turn, your record with each deck and against each archetype, and what the
real tournament metagame looks like next to it.

- **Nothing leaves your computer.** No account, no upload; the dashboard
  runs on your own machine and answers nobody else.
- **Free, with no account.** The tracker is free now and later, and
  nothing free asks you to sign up. A Microsoft Store build of the same
  app, free at first and priced later, and, later still, an optional paid
  tier are planned; the [roadmap](ROADMAP.md) says what each one is.
- **Read-only towards both clients.** It reads their log files and never
  writes to anything Arena or Magic Online owns.
- **Nothing to configure for Arena.** It finds Arena's log on its own,
  including Steam and Proton installs on Linux.
- **Written advice on your terms.** Deck guides, matchup briefs and
  coaching reports come as a prompt you paste into an assistant you
  already use, or from your own Claude key if you set one.

**Em português do Brasil.** O dashboard inteiro, do primeiro clique ao
relatório do treinador, lê em português do Brasil: escolha o idioma na
primeira abertura ou em Configurações. Nomes de cards, decks e arquétipos
ficam como o jogo os escreve, e os prompts que você copia continuam em
inglês: são texto para o modelo, não para você.

## Features

- **Home**: the last session, three things worth a look, and the win rate by week.
- **Live** (Arena): the match in progress, with a keep guide, a read of the
  opponent's likely hand, your remaining library and a sideboard plan between games.
- **Matches**: every match, with a report and a turn-by-turn replay of each game.
- **Decks**: each deck's record over every version, its matchups, and a
  guide that sets your list against the field.
- **Field**: the metagame from real Magic Online and paper tournament results.
- **Coach**: a dated report across every deck, each one measured against the last.

<p align="center">
  <img src="docs/images/field.png" alt="The Field page: the Standard metagame from Magic Online Challenge lists since the format's last reset, archetype by archetype, with your record against each.">
</p>

## Download

Sensei Top runs on Windows 10 and 11 (64-bit) and on 64-bit Linux. Get the
Windows installer or the Linux AppImage from [senseitop.com](https://senseitop.com)
or the [releases page](https://github.com/sensei-top/sensei-top/releases);
[INSTALL.md](INSTALL.md) has the steps for each system. A Microsoft Store
listing of the same app, free, is planned for the release.

The one thing to change in Arena: turn on **Detailed Logs (Plugin
Support)** under Options → Account, then restart it.

## Get started

1. Install and open Sensei Top.
2. Follow the first-run setup: it finds Arena's log, asks where Magic
   Online keeps its game logs if you play there, and downloads card data.
3. Play. Matches appear as they finish; closing the window keeps the app
   recording from the system tray.

## Documentation

The [help pages](https://senseitop.com/help/), in English and Portuguese,
cover installing, the first run, Magic Online, troubleshooting and sending
a problem report. The [user guide](docs/user/README.md) is the reference
behind them: running from source, the command line, every page of the
dashboard, written guides and backups.

## Build from source

You need Python 3.12 or newer with [uv](https://docs.astral.sh/uv/), and
Node with [pnpm](https://pnpm.io/).

    uv sync
    cd web && pnpm install && pnpm start

The dashboard opens at http://127.0.0.1:8000. [Getting
started](docs/user/getting-started.md) has the rest. Before changing code,
read [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).

## Contributing and support

A log-format fix that arrives with the log lines that broke it is the most
useful contribution there is; [CONTRIBUTING.md](CONTRIBUTING.md) says why
and how. Questions, ideas and votes on what comes next go to
[Discussions](https://github.com/sensei-top/sensei-top/discussions), and
the plan is in [ROADMAP.md](ROADMAP.md). To report a vulnerability, read
[SECURITY.md](SECURITY.md).

If Sensei Top earns a place in your routine, donations keep it maintained:
the links are on the project page.

## Licence

Copyright (C) 2026 The Sensei Top authors ([AUTHORS](AUTHORS)).

Sensei Top is free software under the GNU Affero General Public License,
version 3. It comes with no warranty; the full text is in
[LICENSE](LICENSE). The name and logo are not covered by that licence: see
[TRADEMARK.md](TRADEMARK.md).

## Credits

Sensei Top is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC.

Card data and images come from [Scryfall](https://scryfall.com), tournament
results from [MTG_decklistcache](https://github.com/fbettega/MTG_decklistcache) and
[TopDeck.gg](https://topdeck.gg), and archetype definitions from
[MTGOFormatData](https://github.com/Badaro/MTGOFormatData). None of them
produces or endorses Sensei Top. What is taken from each, and on what terms, is
in [docs/attribution.md](docs/attribution.md).
