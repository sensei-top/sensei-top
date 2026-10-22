# Backups

`serve` takes one verified snapshot of the database a day, on a background
thread; pass `--no-backup` to skip it. `sensei-top backup` takes one by
hand, or checks on the last one.

By default the copy lands in a `backups` folder beside the database,
keeping just the current one. Both are configurable, and the setting
persists across restarts:

    sensei-top config --set-backup-dir /path/to/somewhere
    sensei-top config --set-backup-keep 3

A folder you choose inside a git checkout is yours to keep out of the
tree: it holds your whole match history. On Windows, a network folder
(`\\server\share`) is refused for the database and the backups; map the
share to a drive letter and use that instead.

## Restoring one

**Stop Sensei Top first**: quit the app, or Ctrl-C any `serve --watch` or
`ingest --watch`. Then:

    sensei-top restore FILE

It checks the backup before touching anything, refuses one made by a newer
version, keeps the database it replaces beside it as `.replaced`, and
rebuilds your matches from the restored copy. Every step is printed as it
runs. The full sequence, and the manual steps it replaces, are in
[docs/architecture.md](../architecture.md#backups).

Copying a backup back into place by hand is how a stale `-wal` file ends
up beside a restored database, which corrupts it; `restore` moves that
file aside for you.
