# The command line

Everything the dashboard does has a command behind it. From source, run
each one as `uv run sensei-top <command>`; `--help` on any of them lists its
options.

    sensei-top ingest                # read Player-prev.log then Player.log once
    sensei-top project               # rebuild matches/games/turns from raw events
    sensei-top report                # the three metrics, in the terminal
    sensei-top serve                 # dashboard without watching (read-only)
    sensei-top serve --watch         # live mode: watch, rebuild and serve
    sensei-top ingest --watch --project   # headless live mode, no server
    sensei-top cards                 # card names, from the installed Arena client
    sensei-top cards --scryfall      # card names, rules text and legality, from Scryfall
    sensei-top archetypes            # deck definitions, for naming opponents' decks
    sensei-top meta                  # real MTGO/paper tournament results, for the Field page
    sensei-top meta --reclassify     # re-run the classifier over what's stored, no network
    sensei-top backup                # verified daily snapshot of the whole database
    sensei-top restore FILE          # replace the database with a backup (stop serve first)
    sensei-top ingest-mtgo           # read MTGO game logs by hand
    sensei-top mtgo-status           # why aren't my MTGO matches showing up?
    sensei-top guide                 # deck guides in the terminal (list, prompt, import)
    sensei-top brief                 # matchup briefs (list, prompt, import)
    sensei-top rcq                   # the RCQ guide's prompt for the exact 75 you register
    sensei-top config                # keys, Arena log, MTGO handle and log directory, backups
    sensei-top doctor                # what the app can find: Arena's log, MTGO, cards, the database
    sensei-top diagnostics --out FILE  # a zip of the logs and a secret-free report, for a bug report

## Where the data lives

From source, the database is `data/sensei-top.db`; the installed app keeps
it in the folder [INSTALL.md](../../INSTALL.md#where-your-data-lives) names.
`--db PATH`, before the command, points any command at another one.

Raw events are kept verbatim and deduplicated, so re-reading a log changes
nothing (`ingest --from-start` proves it), and `project` is always a full
rebuild: a parser fix applies to every match ever recorded.

Arena wipes `Player.log` on every launch. Running `ingest`, or live mode,
regularly is what preserves your history, since the previous session
survives only in `Player-prev.log`, and only until the next launch.
[Backups](backups.md) protect it from anything that happens to the database
file itself.

Every command appends its warnings to `logs/sensei-top.log` beside the
database; `--verbose` adds the debug lines.
