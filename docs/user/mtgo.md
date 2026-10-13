# Magic Online

While `serve --watch` (or `ingest --watch`) runs, each Magic Online game is
stored once it ends; `ingest-mtgo` reads the folder by hand. Two things
aren't found automatically, so tell Sensei Top both once — in the installed
app, first-run setup and Settings ask for them:

    sensei-top config --set-mtgo-handle YOURHANDLE
    sensei-top config --set-mtgo-dir DIR

MTGO's log never says which player is you, hence the handle. `DIR` is the
directory holding MTGO's `Match_GameLog_*.dat` files. It resolves in this
order, first match wins: an explicit `--dir`/`--mtgo-dir` on the command
that needs it, then a `MTGO_LOG_DIR` environment variable, then the
`config --set-mtgo-dir` value. With none of the three set, MTGO logs are
never read at all.

On Windows, `serve` and `ingest-mtgo` look for the folder MTGO is writing
now and print the command that sets it, when nothing is set or the folder
set is out of date: MTGO moves it on every update.

## Where MTGO matches show up

MTGO matches show up on Home, in Matches and in the Coach. They never
appear on Live, which needs Arena's board-state stream. MTGO's log doesn't
name the deck you played, so a match reaches Decks once you pick its deck
on the match's page. With many matches waiting, Home's "Needs a deck" card
links to **Pick MTGO decks**, which groups them by the saved list that holds
the most cards you played in each; confirming a group picks that deck for
every match in it. Matches no list fits well are left for you to pick one
at a time.

`sensei-top mtgo-status` diagnoses a missing match: which handle and folder
it is using, where each was set, the freshest log file, and how many games
it has stored.
