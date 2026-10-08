# Architecture

## The two stages

```
Player.log ──▶ [reader] ──▶ raw_events ──▶ [projector] ──▶ decks / matches / games / turns
                (dumb)      (append-only)   (all logic)              │
                                                                     ▼
                                                             SQL metric views
                                                                     │
                                                          [api] ──▶ [dashboard]
```

This split is the most important decision in the project, and the reason is not
tidiness. Arena **wipes `Player.log` on every launch**. If parsing happened
during reading, a parser bug would silently destroy data that exists nowhere
else. Because the raw payload is stored verbatim, a parser fix can be replayed
over the entire history — every match ever recorded — by re-running one command.

### Who may know what

| Module | Knows about | Must never know about |
|---|---|---|
| `reader/segmenter.py` | Line shapes, brace depth, timestamps | Matches, games, decks |
| `reader/ingest.py` | Files, byte offsets, inodes, digests | Any Arena semantics |
| `projector/matches.py` | Match/game lifecycle, deck identity | Files, offsets, polling |
| `projector/game_state.py` | Board state accumulation | Files, offsets, polling |
| `live.py` | Orchestration only — runs one then the other | Parsing details of either |
| `review/` | Projected data, `cards`, the corpus | `reader/`, `raw_events`, files |
| `guide/` | `review/`, `metagame/`, one deck's identity | `reader/`, `raw_events`, files |
| `brief/` | One `(deck, archetype)` pairing | Any board state, any game in progress |
| `table/` | The match in progress, via one replay | Writing anything; any completed match |
| `metagame/` | Tournament results, evidence tiers | `Player.log`, `reader/`, `projector/` |
| `api/app.py` | SQL over views; the feature packages' public API | How anything was produced |

If you find yourself importing the projector from the reader, the design has
been violated. `live.py` exists precisely so neither has to know the other.

The six feature packages below the pipeline share one rule the pipeline rows
do not: **they are pure functions of an already-projected database.** None of
them imports `reader/`, none reads `raw_events`, and none writes anything the
projector could rebuild. Each states its own charter in its `__init__.py` —
read those first; they are a few hundred tokens each and they explain the
boundary this table can only name.

Two exceptions, both deliberate and both documented at the site:

- **`table/` reads `raw_events` directly.** It replays the current match at
  request time rather than reading `turns`, because a full `project()` rebuild
  costs ~11.6 s against a 5-second cadence while one match's replay costs
  0.03–0.08 s. It reuses `projector/game_state.py`'s `GameStateTracker` — the
  *same* tracker `project()` drives — so this is one parser with two drivers,
  never a second encoding of Arena semantics. See
  `projector/live_state.py`'s module docstring and
  [current-match.md](current-match.md).
- **`brief/` and the narrative stores persist their output.** An authored
  narrative is not a derivation, so a rebuild cannot recompute it. See rule 6
  in AGENTS.md and the table ownership section below.

## Full rebuild, always

`project()` deletes every derived row and recomputes from scratch. At this
scale that is cheap — measured **0.28 s over 4,595 events**, roughly 60 µs per
event — and it removes an entire class of incremental-state bugs.

Deletion order matters and is fixed by foreign keys:

    turns → games → matches → decks
    (card_events and turn_zones, keyed on (match_id, game_number), go first too)

The rebuild runs inside one explicit transaction, so readers (the API, the
dashboard) keep seeing the previous snapshot until it commits. A half-rebuilt
projection is never visible.

Because the cost scales with *total history* rather than with new rows, live
mode throttles rebuilds separately from reads — see below.

## Live mode's two cadences

`LiveIngester` runs Arena's own ingest and rebuild loops below. MTGO is a
second, independent ingest leg on the same `LiveIngester`, not a second
watcher, and it has two parts. Its game logs (`_poll_mtgo`) are checked every
2 s and stored once a game ends (see "MTGO's game logs" below). Its deck
folder (`_poll_mtgo_decks`) is polled every 30 s (see "The MTGO deck folder"
below). Rows from either ride Arena's own rebuild gate once they exist, the
same as any other dirty poll.

`LiveIngester` runs two loops at different speeds, deliberately, and — since
the rebuild's own write lock measured 5.7 s on a real database — on two
separate threads rather than one:

- **Ingest, every ~1 s, on its own thread and its own connection.** Cheap:
  seek to the stored byte offset, read what is new. Frequent reads are what
  keep the reader ahead of a log Arena may truncate at any moment. Splitting
  this onto its own thread (`ingest_once`, driven by `run_forever`'s inner
  `_ingest_loop`) is what keeps a rebuild in progress on the other thread from
  blocking the next log line — the old single-loop design ran ingest and
  rebuild back-to-back on one thread, so a rebuild's write lock (or even just
  its lock-free parse phase) delayed every new line until it finished.
- **Rebuild, gated to a duty cycle, `project_every` (default 5 s) as a
  floor.** New rows mark the projection dirty; a later tick does the work.
  Rebuilding on every ingest would be waste today and unaffordable after a
  year of play — but a full rebuild's own cost grows with total history, and
  once it outlasts `project_every` (measured: ~16 s a rebuild against a 238k
  event, 1.33 GB database), the old fixed threshold stopped doing anything:
  every dirty poll already found `elapsed >= project_every` true, so the
  watcher rebuilt back-to-back, pinning a core for the life of the process.
  `project_if_due` (`live.py`) instead gates on
  `max(project_every, _last_duration * duty_factor)` — `duty_factor`
  (default 1.0, CLI `--duty-factor`) holds the watcher to roughly a
  `1/duty_factor` duty cycle (~50% at the default) measured off the
  *previous* rebuild's own wall time, so the cost stays a fixed fraction of
  real time as history grows instead of consuming a whole core continuously.
  (The default was 4.0/~20% until the Current match tab went Arena-only —
  see `docs/current-match.md`'s "A second source: MTGO" — trading CPU duty
  for the tab's own latency: a measured 145 s round trip between two Arena
  rebuilds roughly halves to ~58 s at the new default.)

**One exception to the rebuild gate**: `has_match_boundary`
(`projector/matches.py`) forces an immediate rebuild on a new match room,
regardless of `project_every` or the duty-cycle gate. The match boundary is what puts a deck
on the Live page, and the real gap between a room opening and the
first mulligan offer measures ~11 s in captured play — waiting out even the
`project_every` floor on top of the ingest tick would eat a meaningful slice
of that, let alone a duty-cycle gate that can legitimately stay open for a
minute or more once the database has grown. Now that ingest runs on its own
thread, that boundary rebuild no longer delays the offer it exists to protect:
the mulligan offer itself still reaches `raw_events` within one ingest tick
even while the rebuild the room opening triggered is still running — only the
*projected* view of the match waits, and `table/live.py`'s own replay routes
the opening-hand read around that wait rather than through `matches`/`turns`.
A completed match carries the same event type and gets the same early rebuild
as a side effect, which is a bonus rather than a case worth excluding. A
second exception, `has_draft_boundary`, went with the draft assistant
(2026-10-01).

**No Arena log yet** (plan 6, D10). `serve --watch` with no `--file`, no
`$MTGA_LOG` and nothing autodetected starts anyway: `LiveIngester.log_path`
is `None`, one WARNING says so, and Arena's side of each ingest pass does
nothing while MTGO's legs run as usual. The watcher asks
`live.resolve_arena_log()` (the one resolver, a wrapper over `arena_config.resolve_log()`:
`$MTGA_LOG`, then `[arena] log`, then autodetection)
once per `log_resolve_every` (60 s), the first look 60 s after the
start. When it finds a file the file is read as any new one is, from offset 0,
with the previous-session recovery on that first pass. The reader's role is
unchanged (the resolver is the reader's `default_log_path`). A missing
`$MTGA_LOG` path also waits (it counts as nothing found). An explicit `--file`
that does not exist still exits, and `ingest --watch` keeps its exit.
`GET /api/live` carries `arena_log` (home written `~`, `null` with no watcher
or no log yet); the API process cannot ask the
child, so it runs the same resolver.

**MTGO's game logs are stored once a game ends** (`_poll_mtgo`; plan 3, D2).
MTGO writes its game log several times a minute during a match, every write
an append (103 of 103 in one measured Bo3 on the VM, plan 12 S2), and each
stored row is the whole file (see "MTGO's storage arithmetic" below). Storing
every write would put about a hundred rows per match into `raw_events` and
keep the rebuild running at the duty cycle's pace for the whole session, for
a source the Live page does not show
(`migrations/040_arena_only_current_match.sql`). So the leg checks the folder
every 2 s and holds a changed file back until one of two things is true:

- **Its last game names a winner and the file has been quiet 5 s.** Whether
  the last game names a winner is the projector's answer
  (`projector/mtgo/parse.py::last_game_decided`); the reader only reports
  which files moved and stores the one it is handed, and `live.py` combines
  the two (non-negotiable 1). The 5 s keeps a row from catching a write half
  done: MTGO's own, or a copy's when the folder is mirrored, as the author's
  is from a VM through a share `robocopy` fills.
- **The file has been quiet 10 minutes**, whatever its last game says. A
  disconnect, a crash or a game that ends with no winner line still lands, as
  an unfinished game, which the projector already reads.

Quiet alone cannot tell a finished game from a long think: in the measured
match one mid-game pause lasted 36 s and the gap between games 46 s, and a
turn has no upper bound. Quiet is measured on the watcher's own clock, from
the check that first saw the file's current size and mtime, never from the
mtime itself: a copied file carries the other machine's clock. The result is
about one row per game, each marking the projection dirty for the next
ordinary rebuild. There is no boundary rebuild: an MTGO match never becomes
the current match, however fast it is projected (`has_mtgo_boundary`, which
forced one, went with the Current match tab's MTGO support).

**A mirrored folder can fold two games into one row.** When the folder is a
copy, as the author's is (a `robocopy` in the VM fills the share once a
minute), a game's end and the next game's first line can reach the copy in
the same pass. The copy then never holds a file whose last game names a
winner, so that game gets no row of its own; the next row, at the next
game's end, holds it, and nothing is lost. Measured on one real Bo3 (plan 3,
phase 10): two rows for three games, each landing 6–7 s after the copy
received the write. On such a setup a row lands up to about a minute after
its game ends, the copy's own interval. Not yet run against MTGO's own
folder, where the next game's first line is written only once that game
starts (46 s after the previous one ended, in plan 12's measurement).

A file counts as read (`ingest_state`) only once it is stored, so a watcher
stopped mid-game leaves it for the next one. Its identity token is
`<st_ino>:<st_mtime_ns>` (the inode alone before plan 3), so the first run
of this code over an existing database reads every stored game log once
more and stores nothing new: `ingest-mtgo` reports "0 new, N duplicate".
The watcher's first pass stores
every changed file at once, decided or not: it catches up whatever was
written while nothing watched. `sensei-top ingest-mtgo` does the same by
hand, and a running watcher's `project_if_due` notices rows another process
stored (comparing `raw_events`' high-water mark to what it has projected
through) and rebuilds for them on its next due poll.

`--no-mtgo` disables the MTGO leg entirely, deck folder included. Otherwise
the directory resolves in order — an explicit `--mtgo-dir`, then
`MTGO_LOG_DIR`, then `[mtgo] dir` in config.toml
(`mtgo/config.py::resolve_log_dir`) — with no autodetection at any step:
`mtgo_dir` is `None` when none of the three is set, which is the steady state
for an Arena-only install, not a failure.

**MTGO's deck files are polled, every 30 s** (`_poll_mtgo_decks`,
`deck_poll_every`; plan 12, D8 and D17), from two folders: `[mtgo] deck_dir`,
where the user's exported `.dek` files sit, and `[mtgo] dir` itself, where
MTGO keeps its deck store (`grouping *.xml`) beside the game logs.
The game logs in `dir` keep their own rule above; this poll takes only the
two deck file kinds from it, and reads one folder once when both settings
name it. A deck file is stored whenever it changes, with no wait for quiet,
because it changes only when the user saves one. An idle poll costs one
`stat()` per file and writes nothing:
`reader/mtgo_decks.py` skips a file whose identity
token (inode and mtime) and size match `ingest_state`, and the rebuild is never
kept running. And the user expects a deck they just exported to be in the
picker without a restart. The first poll runs on the watcher's first ingest
pass; a folder whose read fails is logged and counted, the other folder is
still read, and the next beat tries both again. `sensei-top ingest-mtgo` reads
the same two folders by hand (`dir`'s groupings whenever it reads `dir`). A
file read while MTGO is still writing it is stored as it was, and the finished
file lands as a new row on the next beat, so whatever decodes these rows
tolerates a payload that does not parse: `projector/mtgo/decks.py` warns about
it by file name and skips it. The export folder resolves in order —
`--mtgo-deck-dir`, then `MTGO_DECK_DIR`, then `[mtgo] deck_dir` in config.toml
(`mtgo/config.py::resolve_deck_dir`) — and is never guessed: `None` is the
normal case, not a failure. The store needs no setting of its own; it is read
wherever `dir` is, and `--no-mtgo` skips it with the rest of the MTGO leg.

The boundary check scans `raw_events` after the watermark of the last
committed rebuild, stored as `_projected_through` on the `LiveIngester` and
persisted to `projection_state.projected_through_id` so a process restart
restores it instead of resetting to 0 — which would otherwise force the first
boundary check after a restart to scan every row ever ingested rather than
just the tail since the last rebuild.

A failing poll is recorded and the loop continues. A watcher that dies silently
during a session is worse than one that logs an error and keeps going.

**`serve`'s other threads are not the watcher's.** The archetype refresh
(once, at startup), the reference refresh (every five minutes), the
corpus refresh (a tick every five minutes; plan 14) and the daily backup
each run on a thread of their own, with a connection of their own,
whether or not `--watch` is given, and each has a flag that turns it off:
`--no-archetype-refresh`, `--no-reference-refresh`,
`--no-corpus-refresh`, `--no-backup`. None of them reads a log. The
corpus refresh is the one that reaches outside sources on a schedule,
and its cadences are each source's, not the tick's
(`docs/metagame.md`, "Fetching the corpus"). How each shares the write
lock with the watcher is under "Naming the opponent's deck" below.

**The watcher is a child process, and it dies with `serve`** (`procs.py`;
plan 3, S5). `serve --watch` runs it as `live.WatcherProcess`, so a rebuild
never contends with the API for one interpreter's GIL ("What a turn snapshot
holds" below). `serve` can end three ways, and each has its own mechanism.
An orderly shutdown (Ctrl+C, or a SIGTERM that uvicorn turns into one) stops
the watcher from the app's lifespan, because uvicorn re-raises SIGTERM once
its own shutdown is done, before anything after `server.run` would run. On
Linux, a `serve` killed outright is noticed by the kernel: the child set
`PR_SET_PDEATHSIG`, and it is started with `fork` rather than Python 3.14's
`forkserver` default, since the signal watches the child's OS parent. On
Windows, the child sits in a Job Object that kills it when `serve`'s handle
to the job closes, which `taskkill /F` does too. macOS gets the first only.
A SIGTERM to the whole process group (`kill -TERM -- -<pgid>`, what the
overnight driver sends) is the orderly shutdown with the watcher already
dead, the same stop a watcher that died alone gets. Both used to hang
`serve` for good: the stop signal was a `multiprocessing.Event`, and its
`set()` waits for every sleeper to wake, the dead child's bridging thread
among them. It is a one-way pipe now, which a dead reader cannot block
(`live._run_watcher`). If the drain of the child's log queue times out,
because the child died holding the queue's lock mid-write, `stop()`
cancels the join that would otherwise hang the interpreter's exit and logs
a warning that the child's last records may be lost. A watcher that dies
alone, found after plan 3's real-match check, is noticed now: a monitor
thread beside the drain waits on the child's sentinel and logs one ERROR
when it dies on its own (after a short grace for the exit codes a group
SIGTERM or Ctrl+C give, so a normal shutdown logs nothing), and `/api/live`
reports `watcher_stopped`; `serve` keeps serving and does not restart the
child (plan 6's shell supervises; `docs/status.md` keeps the open row).

## Storage

SQLite, one file, WAL mode — one writer and many readers, zero setup, and the
whole database is backed up with `VACUUM INTO` (see "Backups" below), never
`sqlite3.Connection.backup()`: that page-stepped API restarts whenever the
source is written to, and this project's watcher writes every second, so it
could livelock. `VACUUM INTO` is one statement producing a consistent,
self-contained, compacted snapshot instead.

- **Raw SQL in numbered migration files**, never an ORM. The schema is small
  and worth reading at a glance.
- **Forward-only.** No down-migrations; derived tables are rebuilt rather than
  migrated backwards.
- `schema_version` records what has been applied. Each migration runs in its
  own transaction and rolls back as a unit on failure.
- **Applied at a process's startup, never mid-run.** `open_database()` is for
  a one-shot command's connection and for `serve`'s startup, which migrates
  once before any thread or process starts. Everything `serve` opens after
  that (the watcher's ingest thread, the backup check, the refresh loops, the
  bulk-stats child) uses `connect()`. `serve` runs from the working tree, so
  a connection that migrated an hour in would apply whatever migration file
  had appeared since: uncommitted, unreviewed, under code that doesn't
  know the new schema. That happened once, to 047, through the backup
  check. Pinned by `tests/test_backup.py::test_scheduler_never_migrates` and
  `tests/test_live.py::test_only_the_watchers_startup_migrates`.
- `executescript()` is deliberately avoided — it issues an implicit COMMIT and
  would break per-migration atomicity. `_split_statements()` splits on `;`
  after stripping comments, since comments legitimately contain semicolons.

Connections use `isolation_level=None`, so transactions are explicit `BEGIN` /
`COMMIT` with `ROLLBACK` in an `except`. Nothing relies on implicit commits.

**MTGO's storage arithmetic is different from Arena's.** Arena's reader
seeks to a byte offset and stores only new lines. MTGO's has no resume path
(`reader/mtgo.py`'s module docstring): each time it stores a game-log file it
stores the whole file, base64-encoded, as a new `raw_events` row, and the
projector keeps the longest payload per match. Since the watcher stores once
per game ("Live mode's two cadences" above), a match's rows add up to the
file's size at the end of each game: at most the number of games times the
final file. A leg that stored every write, as this one once did, would put
about a hundred rows into a measured Bo3, and a match's total would grow with
the square of its length.

Storing only the bytes past the previous row (delta rows) was deferred until
MTGO was shown never to rewrite what it had written. It now has been, on
MTGO's own folder rather than the copy (plan 12 S2), but plan 3 chose whole
rows once per game instead (its D2): the payload model stays as it is, and
the arithmetic above is linear without it. Revisit only if payload volume
becomes a measured problem.

### Adding a migration

Create `src/sensei_top/migrations/NNN_name.sql` with the next number. Never
edit an applied migration — someone's database already ran it. When another
branch is open, the next number may already be taken there:
[branching.md](branching.md), "Migration numbers". Verify the new one applies
to an **existing** database, not just a fresh one:

    sqlite3 data/sensei-top.db "SELECT * FROM schema_version;"   # before
    uv run sensei-top project                            # applies pending
    sqlite3 data/sensei-top.db "SELECT * FROM schema_version;"   # after

### Backups

`src/sensei_top/backup/` takes one `VACUUM INTO` snapshot of the whole
database at most once a day — via `sensei-top backup`, or automatically
from a background thread while `serve` runs (`--no-backup` to skip it).
`sensei-top backup`, like every subcommand, applies any pending migration
when it opens its connection; the scheduler inside `serve` relies on the
migrations `serve` applied at startup and never applies one itself (see the
schema notes above). Either way a backup photographs the schema the running
code expects.

**Destination and retention**, each resolved independently, first match
wins: `--dir`/`--keep` on the command line, then `$SENSEI_TOP_BACKUP_DIR` (`--dir`
only), then `[backup]`'s `dir`/`keep` in `config.toml`, then a `backups`
folder beside the database and `keep = 1`. Deriving the default from `--db`
rather than hardcoding `data/backups/` is what keeps AGENTS.md's mandatory
`--db /tmp/check.db` verification runs harmless — a scratch database gets a
scratch backup folder next to it, never anywhere near the real one. `backup`
and `config --set-backup-dir`/`--set-backup-keep` share this resolution and
the same `config.toml` the MTGO handle, the `[arena]` table and the
file-held credentials live in (a key goes to the system keyring first when one
exists).

**Slot naming and rotation.** Slot 0 is `<db name>.backup`; older ones are
`<db name>.backup.1`, `.2`, and so on up to `keep - 1`. A run shifts existing
slots oldest-first (`keep-1 <- keep-2 <- ... <- 0`) before publishing the new
copy into slot 0, and prunes any numbered slot a shrunk `keep` left behind.
Every deletion and rename targets a path `slot_path()` itself reconstructed
from the configured directory and the db's own name — never a glob — so a
user's own same-looking file in that directory is never at risk.

**Every write lands in a pid-suffixed temp file first**
(`<db name>.backup.tmp.<pid>`, in the destination directory so the final
`os.replace()` is atomic rather than a cross-filesystem copy). Only a
*verified* temp file is ever renamed onto a real slot; a failed `VACUUM INTO`
or a failed verification leaves the existing backup completely untouched,
and the temp file is unlinked on every exit path.

**The copy is a rollback-journal database, not a WAL one.** `VACUUM INTO`
writes a fresh file at SQLite's default journal mode whatever the source is
in; `PRAGMA journal_mode` on a backup of this database returns `delete`
(measured). Nothing needs doing about that — `open_database()` sets
`journal_mode=WAL` the first time it opens a restored file — but it is why a
slot is a single self-contained file: no `-wal` or `-shm` ever appears beside
a backup, including during verification, which opens the temp as
`immutable=1`.

**Verification is three cheap invariants, not `PRAGMA quick_check`, by
default:** the file's size against its own `page_count * page_size` (catches
a truncated or short write), the copy's `schema_version` against the
source's, and its `raw_events` row count against the source's (never fewer).
`quick_check` is opt-in via `--deep-verify` — measured at **67.7 s on the
real 1.7 GB database**, which roughly doubles a run for a corruption mode the
three cheap invariants already make unlikely (a bit flip deep inside a
b-tree page, not a truncation or a copy of the wrong file).

**An advisory claim, not a lock.** `backup_state.running_since`/`running_pid`
stop two runs from wasting a copy on each other; a claim older than 6 hours
is taken over with a warning naming the abandoned pid. What actually keeps a
half-written backup from being mistaken for a good one is the
temp-then-verify-then-`os.replace` sequence above, not the claim.

**WAL interaction: documented, not mitigated.** `VACUUM INTO` holds a read
transaction for its whole duration, so frames written at or after its
snapshot cannot be checkpointed until it finishes, and `data/sensei-top.db-wal`
grows while the watcher keeps writing. Estimated, not yet measured: each
`project()` rewrites ~50–70 MB of frames with churn, and the live-mode
rebuild gate is `max(--project-every, duty factor × last rebuild)` — with
the default duty factor now 1.0 and a full rebuild at ~13–23 s, a backup
window of a few minutes plausibly overlaps 4–10 rebuilds, roughly
200–700 MB of WAL. (The first estimate here, 150–350 MB, assumed the old
duty factor of 4.) Every run records its real duration in
`backup_state.last_duration_ms` (a by-hand `sensei-top backup` also prints
it as `Took:`); the WAL peak is recorded nowhere and needs watching
`data/sensei-top.db-wal` during a run. It self-corrects logically but
not physically: once the read transaction ends, the next writer's automatic
PASSIVE checkpoint copies the frames home and the WAL is reused, but the
`-wal` *file itself* stays at its high-water mark until a TRUNCATE checkpoint
or a process restart — a ~250 MB `data/sensei-top.db-wal` sitting there afterwards
is normal, not a leak. Running `PRAGMA wal_checkpoint(TRUNCATE)` after a
backup was considered and rejected: it blocks new writers and waits for
readers, so with `busy_timeout=5000` it can stall the watcher's writer for up
to 5 s — violating this feature's own rule that it must never stall
ingestion, to reclaim disk space that costs nothing to leave alone. This also
extends the reasoning below: a backup is a long *reader*, never a long
*writer*, so WAL's one-writer-many-readers guarantee means it never blocks or
delays the watcher at all — the cost is a pinned WAL file, which is disk
space, not latency.

**Restoring is `sensei-top restore FILE`** (plan 6, D19). Stop `serve` and
every watcher first: the watcher is a separate process this CLI does not own,
holding an open connection plus its own `-wal`/`-shm`, and the command notices
one only while it is mid-write (it refuses a busy database; an idle connection
goes unseen). It prints each step as it runs: it opens `FILE` read-only and
runs `PRAGMA quick_check`; it refuses a schema newer than the newest migration
this code ships (migrations only go forward); it checkpoints the live database,
so the `.db` holds everything its `-wal` did, then moves the `.db` and whatever
`-wal` and `-shm` remain aside as `.replaced` (`.replaced.1`, `.2` and so on
when one exists, never overwriting); it copies `FILE` in through a temp name in
the same folder and renames it, so a crash never leaves a half-written `.db`;
then `open_database()` migrates and `project()` rebuilds. Every refusal happens
before anything moves. A failure after a move puts every file back; if even
that fails, the command exits with status 3 and names each file still under a
`.replaced` name, and `serve` must not start until they are renamed back, since
it would create a fresh database in their place. `FILE` is copied, not moved,
so the backup survives. The `-wal` and `-shm` move with the `.db` because a
stale `-wal` beside a restored `.db` is the one way to corrupt it.

The manual steps the command replaces, for developers:

```bash
# 1. Stop everything that writes -- Ctrl-C any `serve --watch` / `ingest --watch`.
# 2. Check you have the copy you think you have.
sqlite3 "file:data/backups/sensei-top.db.backup?mode=ro" \
  "SELECT MAX(version) FROM schema_version;" "SELECT COUNT(*) FROM raw_events;"
# 3. Move the live database aside -- never delete it -- AND take its -wal and -shm
#    with it. A stale -wal beside a restored .db is the one way to corrupt this.
mv data/sensei-top.db data/sensei-top.db.replaced
mv data/sensei-top.db-wal data/sensei-top.db-wal.replaced 2>/dev/null
mv data/sensei-top.db-shm data/sensei-top.db-shm.replaced 2>/dev/null
# 4. Copy (not move) the backup into place, so the backup survives.
cp data/backups/sensei-top.db.backup data/sensei-top.db
# 5. Bring the schema forward and rebuild the derived tables.
uv run sensei-top project
```

To undo a restore, stop `serve` and rename the `.replaced` files back. After a
completed restore that is usually the `.db` alone: the checkpoint folded its
`-wal` in. Rename any `-wal.replaced` and `-shm.replaced` back with it.

The restored copy sits at whatever `schema_version` it recorded; `project`
applies anything newer, and forward-only migrations mean a backup can be
restored into the same or a newer version of this code — never an older one.

## The log file

Every launch appends to `<db dir>/logs/sensei-top.log` (`logs.py`; plan 3,
D10), so a reported problem arrives with the lines that led up to it, and a
scratch `--db` keeps its lines out of the real install's file. A line is UTC
(`2026-10-06T14:03:22.418Z`), then an 8-hex session id per launch, which
tells `serve` from a hand-run `ingest-mtgo` appending to the same file, then
the level, the logger and the message, with the home directory written as
`~`. The desktop shell passes its launch's id to every subcommand it
starts in `SENSEI_TOP_SESSION`, so its `shell.log` and this file merge by
id. Each launch's first line names the version, the subcommand, the
platform and the database, never the arguments: `config --set-key` carries
a credential on argv. The file takes `WARNING` and up, `DEBUG` with
`--verbose`; the console keeps `ERROR`, `WARNING` with `--verbose`; each
handler filters on its own level. Both also take the `INFO` lines of the
`sensei_top.llm` loggers, the cost of each generate call (`docs/llm.md`).
It rotates at 2 MB and keeps five old
files. Logging never stops a command: a file that cannot be opened is one
console warning, and the command runs on.

`serve --watch`'s watcher child writes no file of its own. It hands its
records to `serve` through a queue, and they land under `serve`'s session
id; only a SIGKILL loses what is still queued.

On Windows a file another process holds open cannot be renamed, so a
rotation refused because `serve` and a hand-run command share the file is
silent: the file keeps growing past 2 MB until one process holds it alone,
and the next launch that finds it over the limit rotates it (checked on a
Windows 10 VM, plan 3's phase 6).

Under `--verbose` the file also takes other libraries' `DEBUG` lines, the
`anthropic` SDK's request body among them: a generate call's whole prompt
(`docs/llm.md`).

## Finding the clients' files

Discovery is filesystem only: it reads names, folders and at most one line
of a log, never a client's data, and where nothing is found it answers
`None` rather than a guess (non-negotiable 4).

- **Arena's log** (`arena_config.resolve_log()`, which returns the path and
  its source, and which `live.resolve_arena_log`, `doctor` and
  `cards.arena_card_database_path` all ask): an existing `$MTGA_LOG`, then an
  existing `[arena] log` in `config.toml`, then `reader/ingest.py::default_log_path`
  (`--file` outranks all three, applied by the caller): `MTGA_LOG`, then
  the Steam/Proton prefix in each Steam library (`steam.py`), then on
  Windows `%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log`,
  then macOS's. The watcher reads `Player-prev.log` once at startup, before
  the live file, when it exists (`docs/arena-log.md`, "File handling"); the
  digest makes a re-read free (0 new of 1,269 entries on the real database,
  plan 3's phase 4a).
- **Arena's install** (`arena_install.py`), for the card database. Unity
  writes the folder its managed assemblies load from as the log's first line
  (`Mono path[0] = '<install>/MTGA_Data/Managed'`), so the client itself
  says where it was installed, for Wizards' installer, Steam and Epic alike.
  Under Proton the path is a Wine one, resolved through the prefix's
  `dosdevices/`. `cards.arena_card_database_path()` tries it before
  `steam.py`'s library glob, which covers Steam alone. Reading one line is
  not log semantics, so the module sits outside `reader/` and never touches
  `raw_events`.
- **The config file** (`llm/config.py::config_path`; plan 3, D6):
  `~/.config/sensei-top/config.toml` on Linux and macOS,
  `%APPDATA%\sensei-top\config.toml` on Windows, and `$XDG_CONFIG_HOME` on
  every platform when it is set. On Windows, when only the old `~/.config`
  file exists it is still the one read and written, with one warning per
  process naming the new place; nothing moves it.
- **MTGO's game-log folder** is never guessed (`mtgo/config.py`):
  `--mtgo-dir`, then `MTGO_LOG_DIR`, then `[mtgo] dir`. MTGO moves its data
  folder under `%LOCALAPPDATA%\Apps\2.0\Data` whenever it updates, so a
  configured folder goes stale. On Windows `mtgo/discover.py` finds the
  newest folder there holding `Match_GameLog_*.dat` (by creation time), and
  `serve` and `ingest-mtgo` print it with the `config --set-mtgo-dir`
  command when nothing is configured, or when the configured folder is
  behind it or missing (plan 3, D8). Nothing reads the suggested folder
  until the user sets it, and an explicit `--mtgo-dir` or `--dir` silences
  the suggestion.
- **The MTGO handle** is asked for, because the game log never says which
  player is the user. Research for plan 6 (plan 3's phase 6, on a Windows 10
  VM with MTGO closed) found one local file that names the logged-in user:
  `application_settings` (no extension, about 640 bytes of XML), in the
  `Apps\2.0\Data` tree and under `%LOCALAPPDATA%\Wizards of the Coast`,
  holding the handle once as a login setting. Other files carry player names
  only incidentally: `mtgo_game_history` (binary, per-game player names),
  `Match_GameChat_*.dat` (chat speakers) and
  `PrivateChatChannel_Private_<name>.dat` (whispers, with another player's
  name in the file name). Nothing here reads any of them; whether onboarding
  reads the handle from `application_settings` is plan 6's call.

## Idempotency

Everything is safe to re-run, and this is tested rather than assumed:

- **Re-reading a log inserts nothing.** Each entry's digest is
  `sha256(logged_at, occurrence, payload)`, and inserts use `INSERT OR IGNORE`.
  `occurrence` counts how many times this exact `(logged_at, payload)` pair has
  already been seen *in this read* — content decides identity, not position.
- **`source_file` is deliberately excluded from the digest.** When Arena
  rotates `Player.log` to `Player-prev.log`, the same content reappears under a
  new name; including the filename would duplicate an entire session on
  recovery. The digest function takes no source argument at all, so this cannot
  regress by accident.
- **Payload alone is not enough.** Arena polls some endpoints with
  byte-identical responses, and `EventEnterPairing` emits the same
  `{"CurrentModule":"CreateMatch","Payload":"Success"}` once per match. On one
  real session, a payload-only digest dropped 40 rows across 13 payloads.
- **The tiebreaker used to be `line_number`, and that was wrong.** A line
  number is file-relative, so the same event lands on a different line in
  `Player-prev.log` than in the `Player.log` it rotated from (the rotated file
  carries a different amount of preamble). Measured on a real pair of logs,
  that split 3,842 shared entries into two rows apiece — invisible in every
  derived table keyed by natural key (`matches`, `games`, `turns` all
  overwrite), and visible only in `card_events`, which appends. See
  `reader/ingest.py`'s module docstring for the full account.
- **A poll boundary used to change what an entry digests to.** The live
  watcher calls `ingest_file` roughly once a second, and a fresh `Segmenter`
  per call lost two things at every boundary: the most recent header
  timestamp (which a following request has no timestamp of its own and
  inherits) and the header's context label (consumed by the next bare `{`
  line). A request landing as the first entry of a poll got `logged_at =
  NULL`; the same request read again whole, as `Player-prev.log` on recovery,
  got its real timestamp — a different digest, so it was inserted twice.
  Measured on a real database: 1,649 request pairs stored this way.
  `ingest_state.carry_ts`/`carry_context` (migration 042) now persist that
  state across polls, with `carry_header` (migration 062), the header's
  stamp as written, beside them, restored into the next `Segmenter` before
  its first line (`reader/segmenter.py`'s `carry_state()`/`restore_carry()`); a
  *fresh* read — `from_start`, a rotation, or a truncation — starts from an
  empty carry instead, since the old file's timestamps don't apply to
  whatever replaced it. A poll that stops mid-entry (most often a multi-line
  response) is held back rather than split or discarded: the committed byte
  offset never advances past that entry's first line, so the next poll
  re-reads it whole with the same timestamp and label it would have carried
  uninterrupted — up to a size cap (`MAX_PENDING_BYTES`), past which an entry
  that still hasn't closed is corrupt in some new way, not merely still
  arriving, and is abandoned rather than held back forever.
- **Migration 042 stops the poll-boundary twin going forward, not
  retroactively.** A database ingested before it still holds, for some
  requests, the `logged_at = NULL` row and its fully-timestamped twin as two
  separate `raw_events` rows — append-only, so nothing rewrites them. The
  twin lands at a higher `raw_events.id` than the request it duplicates, out
  of order relative to Arena's own timeline, which can revert state a
  request between the two legitimately changed (e.g. a stale deck name).
  `projector/matches.py`'s `project()` fixes this at replay time instead: a
  pre-pass (`_first_request_occurrences`) keyed on each request's own payload
  `id` (a client-generated UUID, unique per request) finds the first
  occurrence of each one in `raw_events.id` order, skips every later twin,
  and — when that first occurrence's own `logged_at` is `NULL` — borrows the
  twin's, since it is the same request's real header timestamp, not a guess.
  This is retroactive with no re-ingest needed, since it reads straight off
  `raw_events` already on disk.
- **Offset arithmetic is byte-exact.** `reader/ingest.py` reads the file in
  binary mode and advances the offset by the raw line's byte length, not by
  re-encoding an already-decoded (and possibly `errors="replace"`-substituted)
  line — encoding a single invalid byte's `U+FFFD` replacement back to UTF-8
  produces 3 bytes for 1, which used to drift the offset and land the next
  read mid-line.
- **Changing the digest formula changes every digest.** A database ingested
  under an old formula must have `raw_events` rebuilt from the source logs
  rather than topped up — an incremental `ingest` would re-insert every entry
  under its new digest and double the whole table.
- **`card_events` needed its own idempotency guarantee, enforced differently.**
  Every other piece of projected state overwrites on replay (turns by
  `(match_id, game_number, turn_number)`, games and matches by their own
  primary keys), so a duplicate raw event is harmless to them even when
  `raw_events`-level dedup misses it — and it can miss it: two log files can
  overlap far more than a narrow rotation boundary (observed for real: one
  `Player-prev.log` reappeared almost wholesale inside the `Player.log` it
  rotated from). `card_events` accumulates instead of snapshotting, so
  `GameStateTracker` dedupes it directly, keyed on the `ZoneTransfer`
  annotation's own `id` (verified unique per `(match, game)`, never reused for
  different content — see `projector/game_state.py`).
- **Projecting twice yields identical rows**, including `turns`.

## Aggregation: views versus Python

The dashboard's core metrics are SQL **views** (`v_deck_winrate`,
`v_play_draw_winrate`, `v_deck_game_length`, `v_deck_turn_curves`,
`v_deck_identity`, `v_deck_identity_winrate`). API endpoints are thin
`SELECT`s over them; rates are computed in SQL with
`CAST(x AS REAL) / NULLIF(y, 0)`.

`v_deck_identity` (migration `033_deck_identity.sql`) is the canonical map
from a `decks.deck_id` content hash to the Arena deck it belongs to: one hash
resolves to exactly one identity, tie-broken by `deck_guids.last_seen`
(whichever Arena deck used the list most recently owns it) with
`arena_deck_id` breaking an exact tie. `v_deck_identity_winrate` joins it onto
`matches` at the same `(deck_key, deck_id, event_id)` grain `v_deck_winrate`
uses, so the API can still filter by content hash or event before rolling
versions up into one deck. `guide/deck.py`'s `list_identities()` reads
this view rather than grouping by hand. It backs `GET /api/guide/decks`,
which the Decks page and every one of a deck's own pages resolve their
address against (`docs/frontend.md`, "A deck's pages").
`/api/metrics/winrate` reads the same view, though no page calls it, and
adds one row with a null `deck_key` for every match no deck was recorded
for, which takes in every MTGO match.

The line, stated as a rule:

> **Aggregation a `SELECT` can express belongs in a view. Statistics it cannot
> express belong in Python, in the feature package that owns the question.**

A count, a sum, a group-by, a ratio of two counts — that is a view, and a new
metric of that shape owes one. Keeping them there makes every number on the
dashboard checkable with `sqlite3` alone, and keeps the API layer disposable.

What is legitimately Python, and why each one is:

| Computation | Where | Why not a view |
|---|---|---|
| Wilson score intervals | `review/leaks.py:67` | Needs `sqrt` and a z-constant; SQLite has neither without an extension |
| Hypergeometric PMF | `table/keep.py:98` | Needs `math.comb` over a loop |
| Draw-odds complement | `table/hand_read.py` | Sequential product over a variable-length draw |
| Medians and curve shapes | `guide/play.py` | SQLite has no median; the windowing is per-deck |
| Field share, windowed to a format reset | `guide/field.py`, `brief/narrative.py` | The window start is computed from a detected ban date, not a literal |
| Position index | `review/position.py` | A fixed-weight formula over four inputs, deliberately transparent and unfitted |

The test for which side something belongs on is not "is it maths" but **"could
a reader verify this number with `sqlite3` and no Python?"** If yes, it is a
view and a missing view is a bug. If no, it belongs in the package that owns
the question, where its inputs are typed and its assumptions are testable —
and it is expected to carry a comment saying what it computes and why the
formula is the one chosen.

## Who owns which table

Three lifecycles, and confusing them is how data gets destroyed:

| Owner | Tables | Rebuild behaviour |
|---|---|---|
| Reader | `raw_events`, `ingest_state`, `header_date_order` | `raw_events` append-only, the other two updated in place (`docs/arena-log.md`, "Timestamps", for the third); never deleted |
| Projector | `decks`, `matches`, `games`, `turns`, `turn_zones`, `card_events`, `deck_guids`, `opponent_archetype`, `game_decks`, `rank_snapshot` | Deleted and recomputed by every `project()` |
| Format inference | `match_format_fit`, `match_format_inference` | Deleted and recomputed by every `classify_matches()`, which runs right after `project()`; `project()` itself never touches them. MTGO matches only |
| Downloaded reference | `cards`, `card_legality`, `mtgo_card`, `archetypes`, `archetype_fetch`, `meta_event`, `meta_fetch`, `meta_fetch_source`, `meta_deck`, `meta_round_match` | Never deleted — a rebuild must not throw away a fetch |
| Metagame classifier | `meta_deck_archetype` | Deleted and recomputed by every `classify_meta_decks()`, same reasoning as `opponent_archetype` |
| Corpus fetchers | `meta_fetch_hold` | Written only by the mtgo.com and TopDeck fetchers: a refusal, a 429 or a 503 writes the source's row, and a completed run deletes it. `project()` never reads it, and a rebuild leaves it alone |
| The user | `opponent_deck_override`, `mtgo_match_pick` | Never deleted — their own pick for their own match: the opponent's deck for either client, and the user's own deck and format for an MTGO match, which MTGO's log never names |
| Authored prose | `deck_narrative`, `matchup_brief`, `match_narrative`, `leaks_narrative`, `coach_report`, `rcq_guide` | Never deleted by `project()` — written, not derived, so a rebuild could not recompute them |

`meta_event` (downloaded reference) gained three read dates in
`migrations/061_meta_fetch_hold.sql`: `lists_read_at`, when a read of
the event last returned decklists, and `empty_read_at` with
`empty_read_kind` (`'empty'` or `'gone'`), when the latest read returned
none or found no page; a later read with lists clears both. Only the
fetchers write them. An event stored before the migration keeps `NULL`,
never a backfilled date (rule 4), and the event page's read line says
that date was not recorded (`docs/metagame.md`, "When a source empties
an event").

`cards` (downloaded reference) gained `power`, `toughness` and `keywords` in
`migrations/031_card_body.sql` — printed-body fields the draft assistant's
local card grade needed, fetched from Scryfall by `cards.py --scryfall`
alongside the pre-existing `oracle_text`/`mana_cost`/`type_line`/`rarity`
columns, with the same `COALESCE`-protected upsert those already use.
Nothing reads them since the draft assistant was deleted;
`migrations/048_drop_draft.sql` keeps them as part of the card database and
drops every draft table.

**A card's legality is one row per format, in `card_legality`.** Migration
053 made it: `(grp_id, format, legality)` for the seven formats a match can
be played in (`formats.py::FORMATS`), written by `cards --scryfall` from
Scryfall's `legalities`. It replaces `cards.standard_legality`, which 053
copied in as format Standard and 054 dropped. A card with no row for a format
has an unknown legality there, never a guessed one, and `banned` is not
`not_legal`. The name backfill (`cards.py`'s module docstring) fills each
format on its own: a format's row is written when every printing with a value
for it agrees, and left out when they disagree, so a name whose printings
differ only in Pauper still gets the other six. A name is skipped whole only
when its printings disagree on Standard or on `oracle_id`, the sign that two
different cards share it. Unlike the backfill's other columns, legality is
replaced on every run, not only filled: a row the name backfill wrote takes
today's consensus, and a format the printings now disagree on loses its row.
Fill-only froze Reality Fracture's pre-release `not_legal` in Standard on 389
grp_ids, so five of its Standard MTGO matches of 2026-10-04 read as Pioneer.
A grp_id written from its own `arena_id` printing in the same run is never
touched.

Scryfall carries today's legality only, with no history of rotations or bans.
Every read of `card_legality` is a read of today's list: a card banned since a
match was played reads `banned` for that match too, and a card rotated out of
Standard since then reads `not_legal`. "A match's format" below states what
that costs.

**An MTGO-only card has a negative `grp_id`.** `cards` is keyed by Arena's
grpId, and a card with an MTGO printing but none on Arena would otherwise have
no row at all. `cards --scryfall` gives each such card one, under `grp_id =
-(the lowest mtgo_id among its printings)`, filled from the same Scryfall
stream: name, type, cost, colours, rules text, `oracle_id`, and its seven
`card_legality` rows (`cards.py::_write_synthetic_cards`). No new download.
A positive id is always Arena's. A card gets no negative row when a `cards`
row already carries its `oracle_id`, or the name of one of its printings,
unless two oracle cards answer to that name in Scryfall's export. Every
negative row and its legality are deleted and rewritten on each run, in one
transaction, so a card that has since reached Arena loses its negative row.
The MTGO resolver (`projector/mtgo/project.py::_lookup`) takes a name's Arena
row first, the lowest positive id when there are several, and its negative
row only when there is no Arena row. A name with both is left `NULL` with a
warning: a negative row sits beside a positive one only when two oracle cards
answer to the name, and MTGO's transcript gives only the name.

**Authored prose arrives by two paths, not one.** Either a CLI `--import` of an
answer written elsewhere (the prompt/import round trip — `docs/brief.md`), or a
`POST .../narrative` route with a Claude credential configured (`docs/llm.md`).
Both write the same rows; the generated path additionally stamps `model`,
`input_tokens`, `output_tokens` and `cost_usd`, which an imported row leaves
`NULL` rather than `0.0` — zero would claim a fact where there is only an
absence (rule 4). `coach_report` also stamps the two prompt-cache counts,
`cache_creation_input_tokens` and `cache_read_input_tokens` (migration
063), `NULL` on a report written before them; there `input_tokens` is only
the uncached remainder (`docs/llm.md`, "Model, effort, and cost").

`deck_narrative` and `matchup_brief` are stamped with the `list_hash` and
`corpus_commit` they were written about, so a stored artifact can report itself
stale rather than silently disagreeing with a changed 75 or a moved corpus.
`match_narrative` and `leaks_narrative` carry a `context_hash` instead, serving
the same purpose against the evidence they were written from. `coach_report`
carries the `format` it was written for (migration 059), and each report's
progress is measured against the previous report of the same format. A row
written before 059 has `NULL` there, which every reader takes as Standard:
every report before it was a Standard one. Nothing writes that answer back.

**`started_at`/`logged_at` mean different things per source, but are
guaranteed one format.** For Arena, `logged_at` is a real per-line timestamp
parsed from the log and `matches.started_at` is the first such timestamp for
the match; for MTGO, `logged_at` is the game-log file's own mtime
(`reader/mtgo.py` has no per-event timestamp to use instead) and
`started_at` is the first raw event seen for that match's file, not a
client-reported instant — see `docs/current-match.md`'s "A second source:
MTGO" for the consequences. What both sources *must* share, because every
comparison across them is plain TEXT (`v_current_match`, `/api/matches`'
`ORDER BY`, `/api/live`'s `MAX(logged_at)`), is the exact same shape: local,
naive, seconds precision, `T`-separated (`YYYY-MM-DDTHH:MM:SS`), no zone. That
guarantee was violated twice in migration history before landing correctly —
`reader/mtgo.py::_mtime_iso` originally wrote UTC-with-`Z`, and the
migration meant to fix retroactively-written rows
(`migrations/036_mtgo_live.sql`) itself first shipped with a bare SQLite
`datetime()` call that produces a **space** separator instead of `T`,
re-inverting the same class of bug in the opposite direction (a repair
migration, `037_mtgo_logged_at_separator.sql`, fixes a database that already
applied the broken 036). `tests/test_db.py`'s
`test_every_logged_at_and_started_at_is_the_same_shape_on_both_sources` pins
the format end to end so a third variant of this bug fails a test rather than
reaching a real database again.

`opponent_archetype` has a foreign key to `matches`; `opponent_deck_override`
deliberately **does not**. `foreign_keys` is ON, so a reference there would make
the rebuild's `DELETE FROM matches` fail outright, and the whole point of a
manual pick is that it survives every rebuild. A row whose match no longer
exists is harmless: `v_match_opponent` joins to it, it never drives the join.

`mtgo_match_pick` (migration 049) follows the same rule for the same reason:
no foreign key to `matches`, and its `deck_id` is not a reference to `decks`
either, which a rebuild empties and refills. An MTGO deck's id is a content
hash (`projector/mtgo/decks.py::mtgo_deck_identity`), so the rebuild writes
the same id back and a pick keeps pointing at it. `v_match_deck` joins the
pick to MTGO matches only and reads `COALESCE(pick.deck_id, matches.deck_id)`;
`matches.deck_id` itself stays what the projector wrote, NULL for every MTGO
match. The pick is written by one route, `PUT /api/matches/{id}/mtgo-pick`,
which answers 400 for an Arena match, and it is never read by `project()` or
by anything that writes a derived table.

**Filter a deck through `v_match_deck` by match id, never by its
`deck_id`.** A reader that wants one deck's matches, or a set of decks',
writes `m.match_id IN (SELECT match_id FROM v_match_deck WHERE deck_id …)`,
or reads the view once and groups in Python. It never joins the view and
then filters `md.deck_id` against a set: that column is the `COALESCE`
above, and no index serves it the way `idx_matches_deck` served
`matches.deck_id`. Plan 12's phases 5 and 6 measured that shape at 10 to 100
times slower than the `IN` form, and every reader converted then uses the
`IN` form or one grouped pass. Migration 050's header records the worst
case, `v_deck_identity` on a synthetic database: 18.9 s with the view
joined in as-is, 20 ms rewritten.

Card pictures are downloaded reference data too, but they live as plain
files beside the database rather than rows: the whole card at
`card_images/{grp_id}.jpg` and the card's art alone at
`card_images/art/{grp_id}.jpg`, two caches that never answer for each
other. The API's two picture routes (`GET /api/cards/{grp_id}/image` and
`GET /api/cards/{grp_id}/art`) write them on first request, which keeps
`PRAGMA query_only=ON` the whole truth about the database while still
letting the read-only layer cache. A `.missing` marker, beside where the
picture would be, remembers ids Scryfall has no picture for under any
URL tried; deleting the directory merely re-fetches lazily. Requests are
spaced by Scryfall's published limits and stop for 30 seconds after a
refusal. Arena-exclusive printings (full-art basics, and
similar) have no Scryfall `arena_id`, so each route reads the card's name
from `cards` (its one database read) and retries by exact name before
giving up — a deliberate, known-imprecise fallback: it returns *a*
printing of the card, not necessarily the one Arena rendered. See
`card_images.py`'s module docstring for the full account.

## Two retroactive projections: rank and sideboarding

Both `rank_snapshot` and `game_decks` are new tables over data that was
already in `raw_events` before either existed — a live comparison against
the user's own database found `RankGetCombinedRankInfo` responses and
`ClientMessageType_SubmitDeckResp` events already stored, unread. Projecting
them retroactively over history already captured is exactly what
non-negotiable #2 exists to make possible.

**Rank** (`migrations/023_rank_snapshot.sql`) is a bare, timestamped
observation — `constructed_class`/`constructed_level`/`constructed_step`,
projected in `Projector._handle_rank_response`. It is deliberately **not** a
column on `matches`: Arena polls rank on its own schedule, not once per
match, so "this match's rank" is answered at query time as *the most recent
snapshot at or before `matches.started_at`* (a correlated subquery in the
`/api/matches` routes, and the same logic pre-aggregated in
`v_rank_winrate` for `/api/metrics/winrate-by-rank`) — never written into
`matches` as a derived guess dressed up as a recorded fact (rule 4). Only
an Arena match looks one up: the snapshots come from Arena's log alone, and
an MTGO match's rank is null (migration `046_rank_winrate_arena_only.sql`).

**Sideboarding** (`migrations/024_game_decks.sql`) is the deck actually held
for one game, from `ClientMessageType_SubmitDeckResp` — the boarding
decision as played, not `brief/`'s authored plan for what *should* be
boarded. The event carries no `matchID` and no `gameNumber` of its own
(confirmed by tracing a real capture, not assumed), so
`Projector._handle_submit_deck` parks it and the very next
`GameStateMessage`'s `gameInfo.gameNumber` claims it — the same "park it,
the next real event claims it" shape `_handle_deck_message` already uses for
game 1's own deck (`connectResp.deckMessage`, which is the one deck
`SubmitDeckResp` never covers). `GET /api/matches/{id}/sideboarding` diffs
each captured game against the previous one (game 1's deck for game 2, game
2's submission for game 3) and resolves grpIds to names in one query.

## What a turn snapshot holds

`turns` carries one row per **player-turn** with the scalar counts (life, hand,
lands, permanents, library, per seat); `turn_zones` carries the identities
behind them, one row per card per zone. Both are the state **at the end of that
turn** — there is exactly one snapshot per turn, so no mid-turn or per-step
board can be reconstructed from them. `card_events` is the only intra-turn
ordering there is.

`turn_zones.zone` is one of `hand`, `battlefield`, `graveyard`, `exile`.
`007_board_detail.sql` added the last of those plus `is_tapped`, `power` and
`toughness`, all of which Arena had always sent and the projector had always
dropped. Three rules govern them:

- **`is_tapped` is battlefield-only**, `NULL` everywhere else, because only a
  permanent has an orientation. `NULL` there means "does not apply", not
  "untapped" — those are different statements.
- **Arena never sends `isTapped: false`.** Across the whole real log, 149 game
  objects carry the true and none carry the false; untapping arrives only as
  `AnnotationType_TappedUntappedPermanent` with `tapped: 0`. So the merged
  object goes stale without that annotation, and `_apply_tapped` folds it back
  onto the object. It runs **after** the turn boundary, unlike every other
  annotation: Arena reports the untap in the same message that advances
  `turnInfo` to the new turn's upkeep, so applying it earlier would untap the
  board of the turn that just ended.
- **Exile is a shared zone.** Unlike hand, graveyard and library it carries no
  `ownerSeatId`, so the seat comes off each exiled object's own `ownerSeatId`.
  That makes it follow the battlefield's rule rather than the hand's: an entry
  whose object we never received is dropped rather than emitted as a hidden
  card, because with no zone owner and no object there is nothing to attribute
  it to.

`008_turn_resource_counts.sql` added `self_graveyard`/`opp_graveyard` and
`self_open_mana`/`opp_open_mana` to `turns`, the same way as every other
per-seat count there:

- **Graveyard reuses `_zone_counts`**, the same helper `self_hand`/`self_library`
  already use — `ZoneType_Graveyard` is a real per-seat zone Arena names even
  when empty, so an empty graveyard reads `0`, not the `NULL` an unobserved
  seat gets.
- **Open mana reuses `_battlefield_counts`**, the same helper `self_lands`
  already uses, filtered to untapped lands — and inherits the same asymmetry
  `self_lands` already has: a seat with zero qualifying battlefield objects
  gets no entry in that helper's dict at all, so "tapped out" and "never
  observed your board" both read `NULL`.
- **"Open mana" means untapped lands**, a bluff/interaction-detection proxy —
  not a rules-accurate available-mana count (Arena's mana pool is never
  exposed, see below). It is symmetric across seats, unlike hand/library: a
  battlefield is public information in Magic, so there is no
  hidden-information reason to withhold the opponent's count. This meaning
  never changes here — `turns.opp_open_mana` has a real consumer (the
  post-game report) that a silent redefinition would rewrite history under.
  The live replay behind the Live page (`docs/current-match.md`)
  widens the picture with a *sibling* count instead: `other_mana_sources`,
  untapped non-land permanents with `cards.produced_mana` on file (rocks,
  dorks, Treasures) — `GameStateTracker` only computes it when explicitly
  asked (`mana_source_grp_ids`), which `project()` never is.

`009_drop_opening_hand.sql` later dropped `v_opening_hand` and its supporting
`turn_zones.library_exit_turn` column: Arena only emits a kept hand's zone
transfers after the mulligan decision is already committed, so the
reconstruction never arrived in time to inform anything. That finding is
still true, and does not mean the opening hand is unavailable full stop —
Arena separately logs the hand it *offers* before each mulligan decision,
which `table/opening_hand.py` reads directly from `raw_events` rather than
through the projection (`docs/current-match.md` has the design and why it
has to bypass `project()`).

That same bypass now covers more than the opening hand.
`projector/live_state.py` replays a match's `raw_events` on request and
reads the board state as it stands *right now*, mid-turn — not the last
turn boundary `project()` happened to reach. The reason is a number, not a
guess: a real database's `project()` rebuild measured **~11.6 s** wall
time, already past the 5-second `project_every` default, so anything
sourced from `turns` on a mature database runs roughly one rebuild's
duration stale. Replaying one match alone, bounded by its own room-opening
event, costs 0.03-0.08 s regardless of how much history sits behind it.
That rebuild also runs in its own OS process now (`live.WatcherProcess`),
not a thread inside the API's own process, because a rebuild sharing the
API's GIL taxed every request during it (`live.py`'s module docstring has
the contention numbers). `docs/current-match.md` has the full design.

What is still **not** available: counters, attackers and blockers, the mana
pool, the stack, and any per-step timeline. See [arena-log.md](arena-log.md).

**None of this exists for MTGO.** `projector/mtgo/project.py` writes only
`matches`, `games` and `card_events` for an MTGO match — never `turns`,
`turn_zones`, `combat_*`, `damage_events`, `life_events`, `game_decks`,
`deck_guids` or `rank_snapshot` — and `deck_id` is always `NULL` (the `decks`
rows MTGO does get come from deck files, not from a match: see the last
paragraph of this section). So an MTGO match has no `turns` row at all, not a
row of zeros; everything above this point is Arena-only in practice.
`card_events.grp_id` itself needs more than an exact name match to fill in.
MTGO's transcript spells a token as `"<Base> Token"`, and a double-faced,
adventure or split card by the face that was played: the front face, or the
back one (a transformed face, an adventure, a split card's second half).
Arena's `cards.name` carries the combined `Front // Back`. `_resolve_grp_id`
tries four rules and stops at the first hit: the exact name (`_lookup`, see
"Who owns which table"), a token lookup gated on `type_line LIKE 'Token%'`, a
front-face match (a combined name that starts with the name and `" // "`),
and a back-face match (a combined name that ends with `" // "` and the name).
Each face rule is taken only when exactly one combined name matches, and both
compare exact, case-sensitive text, never `LIKE`. An ambiguous or genuinely
unknown name stays `NULL` (rule 4) with a warning, never a guess. MTGO's `&`
spelling of a split card (*Wear & Tear*) matches none of the four. Where
`grp_id` stays `NULL`, `card_events.mtgo_name` (migration 060) keeps the
transcript's name; a resolved event, and every Arena one, leaves it `NULL`.
It is what lets `infer_formats` set aside an unresolved token or game marker,
which says nothing about a match's format ("A match's format" below).
`games.turn_count` and
`card_events.turn_number`, the two turn-shaped fields MTGO *does* write, are
deliberately not MTGO's own printed per-player turn number (`Turn 1: <H1>`,
`Turn 1: <H2>`, `Turn 2: <H1>`…) — they count player-turns globally, the same
unit Arena's own `turnNumber` already uses, so a consumer pooling both
sources (the coach, `v_deck_game_length`, `review/analyzers/baseline.py`,
`guide/play.py`) reads one unit rather than two
(`projector/mtgo/parse.py`'s "Turn units"). Concretely, each `Turn N: <H>`
*line* MTGO prints is one player-turn, so a game consisting of exactly
`Turn 1: <H1>` and `Turn 1: <H2>` — two lines, one per player — has
`turn_count == 2`, not `1`. Every `review/` analyzer that reads `self_turns`,
a deck-scoped view, or `damage_events` reports a `Gap` for an MTGO match
rather than reading that absence as a real zero (`tests/test_review_mtgo.py`
pins this end to end); the one analyzer with genuine MTGO signal is
`frame.py`'s opening-hand read (mulligan count, on/off the play), sourced
straight from `games`' own columns rather than from `turns`.
(`migrations/035_mtgo_source.sql`'s comment that MTGO writes neither `games`
nor `turns` is stale — it does write `games`. Applied migrations are never
edited, so this paragraph is the correction.)

**MTGO's `decks` rows come from deck files, not from a match.** Two kinds,
both read by `reader/mtgo_decks.py::ingest_deck_dir` from whichever folder it
is given and told apart by file name alone: a `.dek` the user exported
(`[mtgo] deck_dir`, label `MtgoDeckFile`), and a `grouping *.xml` from MTGO's
own deck store, which MTGO keeps beside its game logs in `[mtgo] dir` (label
`MtgoDeckGrouping`). Both are `source = 'mtgo_deck'`, stored verbatim with the
same `ingest_state` skip. A grouping names no card, only `CatId`s, which are
Scryfall `mtgo_id`s; `mtgo_card` (downloaded reference, filled by
`cards --scryfall`) gives each one's name.

`projector/mtgo/decks.py` — which `project()` calls right after `project_mtgo`,
in the same transaction, so a rebuild still deletes and recomputes `decks` as a
whole — writes one row per distinct maindeck among those rows (an older
version of a file is a deck too, since the user may have played it). Only a
grouping with `GroupingType="Deck"` and a `FormatCode` that
`mtgo/formats.py::FORMAT_CODES` maps to one of the seven formats is a deck; a
binder, a wishlist or a Commander or Freeform deck is counted once per rebuild
at INFO level, not warned about. An MTGO row differs from an Arena row in five
ways. `deck_id` is a sha256 over the maindeck's card *names* and quantities
behind an `mtgo-deck:` prefix, never over `grp_id`s, so a printing swap does
not split a deck and an MTGO id cannot equal an Arena one; the sideboard stays
out, for the reason `deck_identity` gives. A grouping's card is named the way
an export names it (Scryfall's `Front // Back` cut to the front face), so a
list saved in the store and exported too is one deck; a `CatId` `mtgo_card`
lacks enters the identity as `[CatId <number>]`. `format` is the grouping's
mapped `FormatCode`, one of the seven strings `mtgo_match_pick.format` takes,
and `NULL` for a list only ever exported, since a `.dek` carries none. `name`
is the newest file's: a `.dek`'s stem or a grouping's `Name`. `first_seen` and
`last_seen` come from the files' modification times, not from any match, so
they say when the list was saved, not when it was played. And a card that does
not resolve to a `grp_id` — a name `_resolve_grp_id` leaves `NULL`
(above), or a `CatId` `mtgo_card` lacks — is left out of `cards_json` with a
warning, one per card per rebuild, never given an invented id (rule 4). The
copies left out are counted in `cards_json`'s `unresolved` key,
`{"maindeck": n, "sideboard": n}`, on every MTGO row (plan 12, D18), so a
reader can tell a list it cannot fully see from a short one; an Arena row has
no such key, since nothing is left out of it. A file that does not parse as a
deck is skipped whole with a warning that names it, since a list missing one
entry would get a wrong identity; its row stays in `raw_events` (rule 2), so
the warning repeats on every rebuild. Neither a deck file nor a game log says
which deck was played in which match, so `matches.deck_id` stays `NULL`, and
linking the two is left to the user's own pick (`mtgo_match_pick`), never to a
projection.

## Naming the opponent's deck

Arena never sends the opponent's decklist (see
[arena-log.md](arena-log.md) trap 11b), so it is inferred from the cards they
revealed. `src/sensei_top/archetypes/source.py` downloads rule-based
definitions; `classify.py` evaluates them against what a match showed and
writes `opponent_archetype`. Classification runs immediately after `project()`
in both `cmd_project` and `LiveIngester.poll_once`, because a rebuild deletes
its output — it is part of finishing the rebuild, not a separate job.

Naming a match at all needs its format first, because definitions are per
format and so is the corpus. "A match's format" below says where each
match's format comes from and how the classifier uses it.

The label itself is a **view**, `v_match_opponent`, layering
`manual override > classified archetype > colours and a signature card`
(`classified archetype` itself is now two evidence sources combined — see
"A second evidence source" below — but the view only ever sees one written
verdict per match, so this layering is unchanged). It is
a view rather than a stored column because it depends on `cards` and
`archetypes`, which the projector does not own and which the user may populate
long after a match was projected: a column would read stale until the next
rebuild, and a view is always current. In the moment between `project()` and
`classify_matches()` committing, the label degrades to the colours layer rather
than showing a blank. Since `032_corpus_naming.sql`, that colours layer also
carries up to three revealed nonland cards (`opponent_signature_cards`), not
just one — genuinely unnamed matches (no rule definition, no corpus
archetype) now say more than a single card's worth.

`serve` also refreshes the definitions on a background thread with its own
connection, so the process briefly has two writers. WAL plus the existing
`busy_timeout=5000` covers it, and both writes are short. `cli.py`'s
`_start_reference_refresh` is a writer by the same argument: its own
connection, ticking every five minutes, and its Arena-card step
(`cards.refresh_arena_cards`) only ever inserts the handful of grpIds an
Arena patch actually added, so the write stays short even though the thread
itself never stops. A write that loses to the rebuild's 5.7 s lock is caught
by the loop and retried on the next tick. The corpus refresh (plan 14) is a
writer too, on its own connection, with one difference: it waits for the
lock rather than losing to it. Its connection sets `busy_timeout` to 60 s
(`cli.py::_CORPUS_BUSY_TIMEOUT_MS`), because the watcher's rebuild has held
the write lock 5.7 s, a busy error would cost the run and then the source's
hour (D12), and nothing waits on this thread. Its own writes are short: each
event's store, and `reclassify_corpus`, which reads every corpus deck first
and then replaces every classification in one transaction. Measured on a
copy of the real database (458 events, 11,685 decks, 2026-10-05): the
reclassification took 2.9 s, of which the write transaction held the lock
0.05 s, and dedup took 0.15 s in all. The daily backup's own background
thread (see "Backups" above) is yet another writer by the same argument, but
for a different reason: its only writes are two tiny `backup_state` upserts
before and after the multi-minute copy, so it is a long *reader*, not a long
*writer* — WAL's one-writer-many-readers guarantee means it never blocks or
delays the watcher at all, no matter how long the `VACUUM INTO` itself
takes.

`v_match_opponent` (and `v_matchup_winrate`, unioned across the matches of
one row: one key, deck, source and format) also carry `opponent_colors`: the
colours the opponent actually *revealed* (`v_opponent_cards.colors`), never
the archetype's assumed colours — a classified match can be all colours its
definition allows while the opponent has only shown one.
`v_opponent_cards.colors` is `''` both when only colourless cards were
revealed and when revealed cards' colours are simply unknown (no matching
`cards` row yet); those two cannot be told apart, so `''` becomes `NULL` at
this column, and the dashboard renders nothing for it — never the word
"Colourless" (rule 4: unknown means `NULL`, never a guess). This is what lets
`ManaPips` (docs/design-system.md) render the real disc-and-glyph symbols
beside an opponent-deck label instead of a parsed-out colour prefix.

An opponent key keeps its spelling (`archetype:<key>`), so an override or a
brief written before formats needed no migration. A key faced in two formats
is two matchups, though. `v_match_opponent` carries the match's `format`
(migration 056), and `v_matchup_winrate` has one row per `(opponent_key,
deck_id, source, format)` since migration 058, with its label chosen per key
and format. Matches with no format share one row per key, deck and source,
never merged into a named format's. `GET /api/metrics/matchups` reads it as
one row per format, key and deck.

### A match's format

**Arena's log names it.** The projector writes `matches.format` (migration
055) from the deck's format and the event id, through
`formats.py::arena_format`. The mapping is Standard only: Arena's Standard
decks, its Standard events and its unqualified ranked ladder are Standard.
Limited, the Arena-only formats (Historic, Alchemy, Brawl, Timeless,
Explorer) and the precon queues are `NULL` by design, with no warning. An
event id that looks constructed and still maps to nothing warns once per
event id in a rebuild, not once per match. MTGO's log never names a format,
so an MTGO match's `matches.format` is always `NULL`.

**An MTGO match's format is read off its cards.** `classify.py::infer_formats`
reads both seats' revealed cards against `card_legality` and writes two
tables, for MTGO matches only (migration 056), both rebuilt in full by every
`classify_matches()` run. `match_format_fit` has one row per format the match
fits: none of its revealed non-token cards is `not_legal` there. A ban does not
rule a format out. `banned` and `restricted` still fit, because Scryfall's
ban list is today's, not the one in force on the match's date.
`match_format_inference` has one row per MTGO match: the inferred format and
a `reason`. The inferred format is the single narrowest fitting format under
`formats.py::BROADER`, a partial order: Standard ⊂ Pioneer ⊂ Modern ⊂ Legacy
⊂ Vintage, Premodern ⊂ Legacy, and Pauper ⊂ Vintage only. Two incomparable
narrowest formats give no format and reason `ambiguous`, never a tiebreak by
pool size. Cards legal in both Standard and Pauper are exactly that case, so
Pauper is only ever confirmed by the user's pick, never inferred.

Every other reason says why there is no inference, checked in this order:
`unresolved_cards` (a card event never resolved, so the match is not judged on
the cards that did), `unknown_legality` (a resolved card with no `cards` row,
or without a `card_legality` row in all seven formats; unknown is never read
as legal), `no_fit` (every format has a card `not_legal` in it), and
`too_few_cards` (fewer than five distinct non-token names, `MIN_REVEALED`).
A match whose cards cannot all be read has no fit rows at all; a
`too_few_cards` match keeps its fit, which is exact, and only the inference
waits. Tokens never count. A resolved token is skipped by its type line, and
an unresolved event whose `card_events.mtgo_name` is MTGO's token spelling
(`"<Base> Token"`) or a game marker (*The Initiative*, *Undercity*) is set
aside rather than blocking the match. A `NULL` `mtgo_name`, from a row
projected before migration 060, still blocks it.

**`v_match_format` is the format every reader uses**, resolved at read time:
Arena's `matches.format`, else the user's MTGO pick (`mtgo_match_pick.format`,
through `v_match_deck`, which applies a pick to MTGO matches only), else the
inference. Its `format_source` says which answered: `log`, `pick` or
`inferred`, and `NULL` when `format` is. Neither the pick nor the inference is
ever written into `matches.format`: `project()` may not read the pick (rule
6). So an unconfirmed MTGO match counts under its inferred format until a
pick overrides it, and the Field page's format caption says how many of a
format's matches were inferred (`GET /api/formats`).

A deck has a format too, for the guide, the brief and its coverage:
`guide/deck.py::identity_format` (`deck_format(conn, key)` for an API key).
It is the deck's `decks.format` as one of the seven (`TraditionalStandard` is
Standard; Draft and any other spelling is none), else the format most of the
deck's matches have in `v_match_format`, a tie going to the most recently
played and then the lower name, else `NULL`.

**The classifier names a match under every format it could be.** An Arena
match is named under its `matches.format`. An MTGO match is named under every
format in its fit that has definitions, so a Modern-shaped match gets Modern,
Legacy and Vintage rows. `opponent_archetype` is keyed `(match_id, format)`
since migration 056, and `v_match_opponent` joins the row for the match's
`v_match_format` format. `classify_matches` never reads the pick, so a
rebuild comes out the same whatever the user has answered. That is also its
limit: **a pick always corrects the format, but the opponent's deck follows
only inside the fit.** A pick outside the match's fit, or on a match with no
fit, finds no `opponent_archetype` row, and the label falls back to colours
and a signature card until the user picks the opponent's deck as well. A
match whose format has no definitions (no format at all, or Premodern, which
MTGOFormatData ships no rules for) is counted `skipped_format`.

**The limit: legality is today's.** A card rotated out of Standard since a
match was played reads `not_legal` there now, so an MTGO match played before a
Standard rotation no longer fits Standard and is inferred as Pioneer, or
broader. A pick of Standard corrects the format, but not the deck name:
Standard is outside that match's fit, so no Standard row was written for it.
A ban has no such effect on the fit, since a
ban never rules a format out. A date-aware rotation and ban history is not
built.

### Ranking by fit, not by raw condition count

`choose()` used to rank archetypes by counting met conditions, with fewer
unknowns as the tiebreak. That let a definition one requirement short of
proof outrank one that never had a second requirement to begin with: a real
match named its opponent "Dimir Harmonizer" off a single generic card (one of
the two the Harmonizer definition needs) for twenty-odd turns, while the
actual signature card — the whole of a one-condition Excruciator definition —
sat unseen. It also never checked a definition's own colours against what had
actually been shown; that wrong guess was green, the opponent was straight
Dimir.

`classify.py` now scores every candidate as a single **fit** in `[0, 1]`:
`proof` (the fraction of a definition's *observable* requirements that came
back met) times `support` (diminishing returns on raw proof count, so one
lone hit never outweighs two independent ones) times `colour_factor` (how
well the definition's own required colours — derived from the local `cards`
table, unioned across an `all` condition or intersected across a `one-of`
one — agree with the colours the opponent has actually shown; a mismatch
demotes fit rather than erasing it, and sharpens as more cards go by without
the missing colour ever turning up). A verdict is only *named* — written to
`opponent_archetype` at all — when the leader clears an absolute fit floor
**and** beats the best *differently labelled* rival by a real margin; a
close call or a genuine tie leaves the match unclassified rather than picking
an arbitrary winner, and `v_match_opponent` falls through to the colours-and-
signature-card layer exactly as it does for any other unclassified match.
`confidence_of()` is gated the same way, on fit and margin rather than a raw
condition count, and a fallback (a family match, not a proved archetype) is
capped below `'high'` by construction.

The constants (fit floors, the margin multiplier, the colour-agreement ramp)
were fitted against a validation pass over real, previously-classified
matches — 21 of 22 kept their label, one (a `'low'`-confidence one-card
fallback hit) moved to unclassified, none flipped to a wrong label. They are
tunable, not derived; if real data disagrees with them, that is information; a
constant should move before a test does (`AGENTS.md`'s testing rule extends to
tuning: read what actually happened before adjusting the threshold that
disagreed with it).

### A second evidence source: the corpus's own decklists

`choose()`'s rule engine is exact but silent on two counts: a new set's
archetypes score zero on every hand-written definition until
`archetypes/source.py`'s downloaded MTGOFormatData catches up, and even a
well-defined archetype's fit saturates fast, because `_fit_score` counts
*conditions* met, not cards seen — a definition with one condition reaches
its ceiling on the first confirming card and cannot be pushed any further by
a fifth or sixth signature card revealed later in the match. Measured against
195 real Standard matches: 46 stayed unclassified, and 38 of those scored
*zero* candidates outright — not a close call the margin gate rejected, but
no rule definition sharing a single card with what was revealed at all.

`archetypes/corpus.py` reads the same metagame corpus `review/consensus.py`
already aggregates into consensus card lists (`meta_deck` /
`meta_deck_archetype`, 10,000-plus real MTGO/paper decklists, already
archetype-labelled by the same rule engine over *complete* decklists — see
`docs/metagame.md`) as a second opinion: a Laplace-smoothed naive-Bayes
log-odds score over card presence, `log P(archetype) + Σ log(P(card |
archetype) / P(card))` summed over every card this match actually revealed.
It strengthens additively with each card (the property the rule engine's fit
lacks), needs no hand-written definition, and is silent by the same
discipline as everything else here (rule 4): `build_prior()` returns `None`
on a corpus with nothing to say, and a machine that has never run
`sensei-top meta` classifies exactly as it did before this source existed.

**The prior is per format.** `build_prior(conn, fmt)` learns only from the
corpus decks of `fmt` (`meta_event.format`), and its reset and `"gone"`
archetypes are that format's too, so a Modern match is never scored against
Standard's archetypes. A format the corpus holds no classified decks for
(the fetch takes Standard and Modern unless asked for another: see "Metagame
data" below) has no prior, and its matches are named by the rule engine
alone. No format is no prior, never Standard's: `api/sql.py` caches one prior
per corpus state and format for the picker, and `table/intermission.py` keeps
one per format for the Bo3 break read, each for the match's `v_match_format`
format.

Ban-awareness is inherited from `guide/window.py` rather than reimplemented:
a banned card is dropped from every count and an archetype the reset killed
(`structural_change`'s `"gone"` verdict) is excluded from the prior entirely,
rather than windowing the corpus to post-reset dates alone. Measured, the
ban-aware full corpus scored 90% precision on 6,773 decks against the
windowed corpus's 82% on 655 — a card-to-archetype association is not a win
rate, so the "never window `meta_*` across a ban" rule (which protects rates
and shares) does not forbid this; a banned card simply never appears in a
live match to begin with.

`classify_matches()` builds one prior per format per run (not per match), for
each format it is about to name a match under, and combines
the two verdicts by **confidence rank, the rule engine breaking an exact
tie** — the more legible answer of the two when both agree. Neither source is
ever changed to accommodate the other: `choose()`, `evaluate()` and
`_fit_score` are untouched, and the corpus source has its own floors
(`CORPUS_MIN_CARDS`, `CORPUS_MIN_ODDS` and the medium/high tiers in
`classify.py`) on an entirely different scale (unbounded log-odds, not a
bounded `[0, 1]` fit) rather than reusing the rule engine's numbers. A
corpus-won verdict is written with `method = 'corpus'`, flows through
`opponent_source` for free (that column already reads `a.method` directly),
and reuses `_archetype_label`/`color_label` so it renders identically to a
rule-named deck. `rank_candidates()` takes the same prior as an optional
argument to nudge (never invent) a candidate's `fit` in the picker's
shortlist; omitted, its behaviour is unchanged from before this source
existed.

Every constant here — `CORPUS_MIN_CARDS = 3`, `CORPUS_MIN_ODDS = 25.0`,
`MIN_CORPUS_DECKS = 8` — was fitted against one snapshot of one player's real
match history and the 15 matches they had manually corrected, the same
"tunable, not derived" discipline the rule engine's own fit floors follow
above. They are expected to move once real behaviour disagrees with them.

### Correcting the classifier: a pick, not free text

The dashboard offers every archetype and fallback definition for a match's
format, ranked by the same fit `choose()` uses, via
`archetypes.rank_candidates()` and `GET
/api/matches/{id}/opponent-deck/candidates`. Unlike `choose()`, which commits
to one verdict or none, this returns everything — a definition the revealed
cards contradict is still worth offering, because the player watched the
match and may know better than a dozen-card heuristic. It is ranked last, at
confidence `'none'`, with a `reasons` entry naming the seen card that ruled it
out when there is one (`_elimination_reason`). Every scored candidate carries
its own `fit` and `reasons` (which cards matched, and any colour the
definition needs that hasn't shown up) — what the Live page's
shortlist and the picker's fit bar both render directly, rather than
re-deriving anything client-side. The picker is offered at every confidence,
not only when the classifier reports doubt: a wrong `'medium'` or `'high'`
guess is exactly as correctable as an uncertain one, so nothing in the API or
the dashboard gates it on `opponent_confidence` any more.

`rank_candidates()` also flags whichever candidate matches the match's
current `opponent_deck_override`, if any, as `picked: true` — a lookup it
already has the connection and match id to do itself, so nothing downstream
needs to re-query `opponent_deck_override` separately. Its one reader is the
picker itself (`OpponentDeckLabel.tsx`), which marks the current pick; every
other surface that needs "the opponent's deck" reads the override through
`v_match_opponent` (where a manual pick outranks the classifier) rather than this flag, so a correction reaches them without
passing through the candidate list at all.

"Rogue" — Magic's term for a deck with no established archetype — is not one
of these definitions, so it never appears in the API response; the dashboard
adds it itself, always last. Picking it stores an override with a `label` but
no `archetype_key`.

`opponent_deck_override` therefore carries an `archetype_key` (added in
`006_deck_picker.sql`) alongside `label`: set when the pick names a real
definition, `NULL` for Rogue. `v_match_opponent` prefers `'archetype:' ||
archetype_key` for `opponent_key` when it is set, so a picked archetype
merges into the same matchup as matches the classifier itself named that
way, rather than splitting off under its own `manual:` key. Migration 006
also deleted every existing override: the free-text "name it" feature it
replaces produced labels with no `archetype_key` and no way to reconcile them
with the picker's candidate list, so the one row that had accumulated was
wiped rather than left stale.

`010_zone_card_detail.sql` widened `v_turn_zones` with `mana_cost`,
`type_line` and `colors` — columns `cards` had held since `003_current_match.sql`
but no view ever surfaced beyond `name`. Nothing new to compute: the join
already happened, and the frontend's zone displays (the current-match tab's
facts panel, the turn-by-turn board) needed more than a bare name to say
anything about a card.

## The match report, and its optional narrative

`src/sensei_top/review/` is a post-projection analysis package, the same
shape as `archetypes/` one stage further out: it reads projected tables and
views, never `raw_events`, and nothing in `projector/` may import it (see its
own module docstring for the two hard rules this implies). `GET
/api/matches/{id}/report` returns its output — deterministic findings and
gaps, recomputed fresh on every request rather than stored.

The report is a postmortem built on the game's own strategy canon (Flores'
role assignment, Duke's damage racing and tempo/card-advantage framing, the
Lichess-style idea of naming the turn that decided a game) rather than log
bookkeeping — see `docs/review.md` for what each analyzer measures and the
article behind it. `review/analyzers/` is a package, one module per concept
in that arc (`frame`, `clock`, `trajectory`, `role_play`, `information`,
`resources`, `baseline`), registered in `review/analyzers/__init__.py`'s
`ANALYZERS` tuple; `match_report.py` runs every entry over one
`MatchSnapshot` and concatenates the results in a stable sort, never
registry order.

**Computed on demand, not persisted — the same reasoning as
`v_match_opponent` above, one step further.** Several analyzers read
`cards.type_line`/`oracle_text` (to tag a card's effect, or classify a
decklist) and `decks.cards_json`, neither owned by the projector and both
possibly populated (`sensei-top cards`) long after a match was projected.
A stored `findings` table would read *wrong*, not merely stale, for every
match analyzed before that download finished. **The analyzers themselves never
touch `sqlite3`** — they are pure functions of a `MatchSnapshot`, which is what
makes them testable from a constructed snapshot with no database at all — every
one has the signature `analyze_*(snap: MatchSnapshot) -> AnalyzerResult`, with
zero database access in `review/analyzers/`.

Query access in this package is confined to five modules with distinct jobs:
`snapshot.py` (the per-match read the analyzers run on, 21 queries),
`leaks.py` (the cross-match population, 6), `consensus.py` (the corpus scan,
3), and `narrative_store.py` / `leaks_store.py` (2 each). `match_report.py`
takes a connection but issues no query of its own — it passes one through to
`build_snapshot` and then runs the pure analyzers over the result.

`snapshot.py` does one read per match, including a same-request
classification of the player's own deck (`archetypes.classify`'s
`complete=True` path, the same one `metagame.classify_meta` runs over a
corpus decklist) and a scan of the metagame corpus for the opponent's
archetype's consensus decklist (`review/consensus.py`).

Every analyzer returns `Finding`s (something observed) and `Gap`s (something
it could not evaluate, and why) — kept as separate lists so a report's
silence is never mistaken for "nothing was wrong" (rule 4). `self_open_mana`
is the sharpest case: NULL means both "tapped out" and "never observed your
board" (migration 008), so nothing here computes an "unspent mana" reading
from it. Combat — attacks, blocks, damage — *is* now analyzed: migration 014
projects `combat_attacks`, `combat_blocks`, `damage_events` and
`life_events` from `gameObjects[].attackState`/`blockState` and
`AnnotationType_DamageDealt`/`ModifiedLife`, verified against a real capture
carved into `tests/fixtures/combat_session.log` (see that migration's own
comments for the traps: Arena reuses annotation ids across different
annotation types within one game, and re-broadcasts the same attack
assertion across several messages). `review/position.py`'s position index —
a transparent, fixed-weight formula over life/board/hand/mana, never fitted
to outcomes — turns that per-turn data into the number `trajectory.py`
anchors a game's turning point to.

**The narrative is the coaching layer over all of this, not a summary of
it** — and this module does not fetch it itself.
`src/sensei_top/review/narrative.py` (formerly `advisor.py`, before that a
live mid-match hint) builds the *prompt*: the match's turn-by-turn shape,
both sides' play sequence, and the report's own findings and gaps, asking
for a full structured review rather than a 250-word note. AGENTS.md
non-negotiable #5 permits an opt-in, user-configured Claude call
(`src/sensei_top/llm/`, `docs/llm.md`) but confines it to that one small
package — `review/narrative.py` stays a pure function of already-projected
data:

- **`build_narrative_context(report, snap, field=...)`** formats an
  already-computed `MatchReport` together with its `MatchSnapshot`:
  per-turn life/hand/board/power/lands for both sides, both sides' resolved
  spells in order, then the findings and gaps. Never a raw zone dump — no
  hands, no graveyards, no exile contents, and `MatchSnapshot` never carries
  the opponent's Arena handle or user id in the first place, so there is
  nothing to leak there even by accident. It ends with an explicit "not
  tracked" block (the stack, counters, attachments, the exact phase or step,
  the opponent's hand) so whoever writes the review is never left to assume
  silence means empty (rule 4).
- **`full_prompt(context)`** prepends the framing that used to travel as a
  `system` parameter.
- **`GET /api/matches/{id}/report/narrative`** returns the stored prose
  (`status: "ok"`) once written, or the prompt to write one
  (`status: "prompt"`) otherwise. **`POST`** on the same path sends that
  prompt through `llm.write_prose` and stores the answer in
  `match_narrative`, when a credential is configured (503 otherwise).
  `MatchReportPanel` renders either state through `GenerateCard`, which
  falls back to plain `CopyPromptCard` with no credential configured. There
  is no *CLI* importer for a per-match review — it is read once, about a
  game already played (`docs/review.md`) — so a stored narrative here comes
  only from the generate button.

The deck guide and the matchup brief follow the same prompt-out pattern and
also store what comes back — `deck_narrative` and `matchup_brief` — and both
additionally accept a CLI `--import`, because those describe a deck rather than
one game and stay useful for as long as the deck does. See `docs/brief.md` for
that round trip.

**The matchup brief still has no generate button of its own**, and that has not
changed — but it is no longer import-only either. `POST /api/guide/{key}/
narrative` writes `matchup_brief` rows as a second effect, via
`brief/from_guide.py::store_guide_matchups`, for every matchup the generated
guide covers. So a brief now arrives by three paths: a CLI `brief --import`, a
CLI `guide --import`, or the guide's generate route. Its own card
(`MatchupBriefCard`) remains `CopyPromptCard`-only, deliberately — a brief is
read while a game is on the clock, which is the worst moment to start a
minutes-long API call.

A malformed answer or import raises `NarrativeError` — the CLI says what was
wrong rather than storing half a guide, and the generate route maps it to a
502 rather than storing anything; the API's own `GET` routes answer `200`
with an honest status for every "nothing to show yet" case — an empty
report, never a broken page.

### Metagame data: real tournament results, not Arena aggregators

The report's matchup context wanted one more input: how the current
archetype is actually performing in the field right now, not just what
defines it. Three sources were evaluated and two were rejected before
`metagame/` was written — its own fetch still has to meet the free-download
standard (reference lookups only, fail-soft, no more than the feature needs;
AGENTS.md non-negotiable #5, in full in [llm.md](llm.md)):

- `mtgdecks.net/robots.txt` disallows `ClaudeBot`, `anthropic-ai`,
  `Claude-Webt`, `GPTBot`, `CCBot`, and a site-specific `MTGMeta-Scraper`
  user agent by name, and carries `Content-Signal: ai-train=no`. That isn't
  rate-limiting; it's the site stating, in the one channel meant for
  automated readers, that this kind of tool specifically should not read it.
- `mtgazone.com` blocks even an unauthenticated fetch of its own
  `robots.txt` (403) — its anti-bot layer refuses the request before any
  policy can be read at all.
- `17lands.com` publishes aggregated play data under a CC BY 4.0 license —
  the right posture, the opposite of the two sites above — but it collects
  from Arena Limited drafts, not constructed. Its data cannot answer a
  Standard matchup question regardless of license terms, so it was rejected
  on coverage, not access **for this feature**. That reasoning still holds
  exactly as written — but it does not generalize to every feature this
  project might build, only to a *constructed* matchup question. The draft
  assistant (deleted 2026-10-01; `archive/draft` tag) asked a Limited pick
  question instead, the one thing 17lands' data actually answers, and reused
  this same access verdict rather than re-litigating it.

Rule 5 draws the line between the sanctioned calls and everything else at
"does this serve the data freely to any request, for the format this project
actually classifies." `fbettega/MTG_decklistcache` clears both bars: MIT-
adjacent GPL-3.0 data served over plain `git`/HTTP, and its `MTGO` and
`MTGmelee` sources are real constructed results, in the formats `archetypes/`
classifies. The fetch follows Standard, Modern and every format the stored corpus
already holds (`metagame/auto.py::followed_formats`); `sensei-top meta
--format X` adds another on demand. `metagame/`
fetches it windowed by date and incremental by blob SHA (the cache is ~157 MB
of history this project mostly does not need); see [metagame.md](metagame.md)
for the evidence-tier rules that constrain what each stored event is allowed to
claim, and for why `archetypes.classify`'s rule engine runs in a different mode
against a full decklist than it does against the dozen cards a live match
reveals.

Two more sources were added later, each read directly and stored through
the same parse and storage path, so the tiers, dedup and the dropped
handles hold for them unchanged: TopDeck.gg's tournament API, with the
user's own free key, for paper events the cache does not carry, and
mtgo.com's own result pages, because the cache lags the site by days.
What each takes, and the terms each was read against, are in
[attribution.md](attribution.md). Since plan 14 `serve` keeps all three
current on a thread of its own ("Live mode's two cadences" above;
[metagame.md](metagame.md), "Fetching the corpus").

## The desktop shell

The desktop app (`desktop/`, an Electron shell) is a parent process that
runs the same `serve` a developer runs, so what it needs from `serve` is a
small handshake and nothing else.

**Start.** `serve --port 0` lets the OS choose the port. Whatever the port,
`cmd_serve` binds the socket itself (host already checked by
`_require_loopback`) and hands it to uvicorn, so the port it reports is the
one it listens on, and a connection made the moment the line prints is
never refused. With `--ready-line`, `serve` prints exactly one line,
`{"listening": <port>}`, to stdout once uvicorn's `started` flag is set.
Nothing else on stdout is a contract: the prose lines around it may change.

**Lifeline.** `--exit-on-stdin-close` starts a daemon thread that waits for
stdin to reach end of file. The shell holds `serve`'s stdin open; when the
shell dies by any means the pipe closes, and at end of file the thread sets
uvicorn's `should_exit`, which runs the lifespan's shutdown and stops the
watcher the way Ctrl+C does. On Linux and macOS the thread blocks in a read.
On Windows it must not: Windows serializes synchronous I/O on a handle, and
while a read was pending on the stdin pipe, the watcher child that
`serve --watch` spawns, which shares that handle, stalled at startup before
running any Python. It ingested nothing while `/api/live` still reported it
alive (measured on Windows 10, 2026-10-07). There the thread polls the pipe
with `PeekNamedPipe` every quarter second instead, and falls back to the
blocking read only when stdin is not a pipe. `procs.py` keeps covering
`serve`'s own children.

**Who owns which file.** To be completed with the shell's phases: the
Python CLI alone writes `config.toml`; the shell's own preferences live in
a file the server never reads.

Pinned by `tests/test_cli.py`, "serve's handshake with a parent process".

### The frozen server

`uv run python scripts/build_server.py` builds the dashboard if `web_dist/`
is older than its sources, freezes the server with PyInstaller
(`desktop/server/sensei-top.spec`, `--onedir`, into the gitignored
`desktop/server/dist/sensei-top/`), then smoke-tests the result:
`--version` equals the pyproject version, `doctor --json` parses, the
frozen executable ingests and projects a fixture, and `serve --port 0
--ready-line --exit-on-stdin-close` answers `/api/health`, reports the
version and serves the dashboard, then exits when its stdin closes.
`--smoke-only` skips both builds and tests an existing dist (`--dist` moves
it). It is not part of `pytest -q`: it takes minutes with a cold web build.
The smoke test runs on Linux and Windows; it writes only inside a
temporary directory, reads a fixture, runs its children with a failing
keyring backend, a temporary config home and no API keys, and starts `serve`
with every refresh job off. On Windows alone, one `doctor --json` run names
`WinVaultKeyring` to prove that backend imports (it reads no credential). On
Linux it checks that no frozen process outlives `serve`.

Each spec line is there for a reason:

- **A console executable, no UPX.** The shell reads stdout, which a windowed
  executable does not have; UPX-packed binaries are what antivirus
  products flag.
- **`copy_metadata("sensei-top")`.** `api/app.py` and `logs.py` read the
  version through `importlib.metadata` (`api/app.py` raises without
  `sensei_top-*.dist-info`; `logs.py` falls back to "unknown"). The spec drops
  `direct_url.json` from the copied metadata: an editable install's names the
  builder's directory. `copy_metadata("keyring")` is needed because keyring
  finds its backends through entry points.
- **`collect_data_files("sensei_top")`.** `migrations/` and `web_dist/` are
  read through `importlib.resources`, so they must sit in the bundle.
- **Hidden imports for `uvicorn` and `keyring.backends`.** uvicorn imports
  its loop, protocol and lifespan modules from strings, and keyring imports
  a backend by name; the analysis sees neither.
- **`multiprocessing.freeze_support()` first in `cli.main`.** The only child
  `serve` starts is `--watch`'s watcher, forked on Linux and spawned on
  Windows. In a frozen build a spawned child is the same executable, and
  without the call it would run the CLI again instead of its target. The
  smoke test starts `serve --watch` and checks that the watcher child
  ingested the fixture (`/api/live` reports events).
- **A generated entry script** (`desktop/server/build/entry.py`), since the
  `sensei-top` console script is made by the installer, which PyInstaller
  does not run.

`sensei-top --version` exists for this smoke test and for the shell.

### Support commands

Two read-only commands answer "what can the app find" and "what do I attach
to a bug report"; the desktop shell drives both.

- **`sensei-top doctor [--json] [--file PATH]`** (`doctor.py`). Reports the
  Arena log's path and source (`flag`, `environment`, `config`, `autodetect`
  or `none`), Detailed Logs, the MTGO directories and whether a handle is
  set, the card counts, the schema version beside the code's, the config
  path and the keyring backend. It never creates, migrates or writes the
  database: that is opened through a `?mode=ro` URI (`connect()` sets
  `journal_mode=WAL`, which writes; a read-only open can still leave an empty
  `-wal` and a 32 KB `-shm` beside a WAL database nothing else has open,
  never touching the main file), and a missing file or table reads as
  `null`, not zero. Detailed Logs is `enabled` when the log's
  first 200 lines carry `DETAILED LOGS: ENABLED`, `disabled` only on a
  `DISABLED` line (never seen in a capture, so untested), `unknown`
  otherwise. The `--json` keys are a contract the shell reads.
- **`sensei-top diagnostics --out FILE.zip [--shell-log PATH]
  [--with-player-log] [--list]`** (`diagnostics.py`). The zip holds
  `doctor.json`, `config.toml` with every `api_key` and `[mtgo] handle` removed (rebuilt
  from the parsed tables, never by text substitution), `row_counts.json`, the app's
  log files and, on request, the shell's log and `Player.log`. Paths inside
  it are written with `~` for the home directory, as `logs.py` writes them.
  The database never goes in. `--list` prints each entry and its size and
  writes nothing; an existing `--out` file is refused.

Pinned by `tests/test_doctor.py`.
