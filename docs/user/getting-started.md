# Getting started

The installed app ([INSTALL.md](../../INSTALL.md)) walks you through this on
first launch. This page is for running Sensei Top from source, and for the
settings behind that setup.

## Requirements

- Python 3.12 or newer with [uv](https://docs.astral.sh/uv/)
- Node with [pnpm](https://pnpm.io/) (dashboard only)
- In Arena: **Detailed Logs (Plugin Support)** enabled (Options → Account).
  Without it the log contains nothing to read.

## Setup

    uv sync
    cd web && pnpm install && cd ..

## Arena's log

The log path is found automatically for Steam and Proton installs and for
Arena's default place on Windows. Anywhere else, point `MTGA_LOG` at the
file (quote it — the path contains spaces):

    export MTGA_LOG="/path/to/SteamLibrary/steamapps/compatdata/2141910/pfx/drive_c/users/steamuser/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"

or store it once with `uv run sensei-top config --set-arena-log PATH`, used
whenever neither `--file` nor `MTGA_LOG` names one.

If your log's dates read day-first, `config --set-date-order dmy` saves
passing `--locale` each time.

## Run

    cd web && pnpm start

Builds the dashboard and starts live mode: the log is followed while you
play, matches appear as they finish, and the page refreshes itself. Always
at **http://127.0.0.1:8000** — both ports are fixed (API 8000, dev server
5173), so the URL is bookmarkable.

The same thing without the build step, from the repository root:

    uv run sensei-top serve --watch

`--interval` sets how often the log is read (default 1 s), `--project-every`
how often derived tables are rebuilt (default 5 s).

`serve` binds loopback only and refuses any other `--host`. It also refuses
requests made on behalf of another website, so a page open in your browser
can't read your match data or act on it, such as starting a paid Claude
call.

## Card names

The log names cards only by number, so run `uv run sensei-top cards` once to
get names. It reads the card database your Arena install already ships, and
falls back to downloading Scryfall's if Arena is not installed here. The
deck guide also needs rules text and format legality, which only Scryfall
has: run `uv run sensei-top cards --scryfall` at least once.
The installed app does this on its own the first time it finds no
rules text.

Next: [the dashboard](dashboard.md).
