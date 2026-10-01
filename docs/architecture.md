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
second, independent ingest leg on the same `LiveIngester` (`_poll_mtgo`), not
a second watcher — but it no longer has a cadence of its own to describe
alongside Arena's two: it reads once, at the watcher's own startup, and
never polls again for the rest of the session (see "MTGO's own ingest leg"
below). Its rows still ride Arena's own rebuild gate once they exist, the
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

**MTGO's own ingest leg reads once, at the watcher's own startup, and never
polls again — not on any cadence at all.** MTGO's own flush cadence measures
~7.4 s (28 size changes over 208 s of a real in-progress match —
`.claude/handoffs/mtgo-source.md`), and this leg used to poll on a slower
clock of its own (default 5 s) to match it. But every flush rewrites the
whole `.dat` file, so a leg that kept polling inserted another full-file-
prefix `raw_events` row (~28 per match) and marked the projection dirty on
every one of those flushes — keeping the ~16 s rebuild running at the duty
cycle's own pace for the entire length of an MTGO session, CPU spent on a
source that, since migration 040 below, can never land on the one page that
latency was ever bought for. `_poll_mtgo` now runs `ingest_mtgo_dir` exactly
once, on this process's first ingest pass, and is a no-op on every pass after
(`live.py`). A match played later in a long-running session needs a
hand-run `sensei-top ingest-mtgo`, or the next `serve --watch`/
`ingest --watch` restart, to reach `raw_events` at all — once it does, a
running watcher's own `project_if_due` notices (comparing `raw_events`' own
high-water mark to what it has already projected through) and marks itself
dirty for the next ordinary rebuild, so MTGO history still lands in
History/Matchups without a separate `project` step, even though landing the
row in the first place is no longer automatic mid-session the way Arena's
leg is. There used to be a third boundary check, `has_mtgo_boundary`,
forcing an immediate rebuild on a *new* game-log file so a new MTGO match
would hit the Current match tab (now the Live page) inside its mulligan
window — deleted along with that window: the page is Arena-only now
(`v_current_match`, `migrations/040_arena_only_current_match.sql`), so an
MTGO match can never
become "current" no matter how fast it is projected. `--no-mtgo` disables
the MTGO leg entirely. Otherwise the directory resolves in order — an
explicit `--mtgo-dir`, then `MTGO_LOG_DIR`, then `[mtgo] dir` in
config.toml (`mtgo/config.py::resolve_log_dir`) — with no autodetection at
any step: `mtgo_dir` is `None` when none of the three is set, which is the
steady state for an Arena-only install, not a failure.

Both boundary checks scan `raw_events` after the watermark of the last
committed rebuild, stored as `_projected_through` on the `LiveIngester` and
persisted to `projection_state.projected_through_id` so a process restart
restores it instead of resetting to 0 — which would otherwise force the first
boundary check after a restart to scan every row ever ingested rather than
just the tail since the last rebuild.

A failing poll is recorded and the loop continues. A watcher that dies silently
during a session is worse than one that logs an error and keeps going.

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

**MTGO's storage arithmetic is different from Arena's, and worth being
deliberate about.** Arena's reader seeks to a byte offset and stores only new
lines; MTGO's reader has no such resume path (`reader/mtgo.py`'s module
docstring) — every poll that finds a changed game-log file re-reads it whole
and stores the **entire current content** as a new `raw_events` row, one full
payload per distinct size the file passes through while a match is live. So
total bytes stored for one match is the **sum of every prefix size** the file
ever reaches, not just its final size: if a match flushes at a roughly fixed
cadence (measured ~7.4 s) for a duration `d`, the number of flushes grows
linearly with `d` and each flush's *payload* also grows roughly linearly with
`d`, so total stored bytes for that match grow roughly with `d²` — a quadratic
range, not linear, in how long a match runs. For real matches (measured: 28
size changes over 208 s, `.claude/handoffs/mtgo-source.md`) this stays a few
hundred KB total, nowhere near a problem; it would only matter if match
durations or flush frequency changed by an order of magnitude.

The escape hatch, deferred rather than built: store only the **delta** past
the previously-seen size instead of re-storing the whole file. Not built here
because it rests on an assumption this project hasn't verified — that MTGO
only appends and never rewrites bytes earlier in the file on a later flush —
and the transport in use (`robocopy /mon:1`) rewrites the destination file
wholesale on every sync, which makes trusting that assumption from the
mirrored copy alone risky. **Verification requirement before building it**:
trace real flush-to-flush byte diffs on a live match directly against MTGO's
own log directory (not the mirrored copy) and confirm every earlier byte
range is stable across flushes. Revisit only if payload volume actually
becomes a measured problem — don't build it speculatively.

### Adding a migration

Create `migrations/NNN_name.sql` with the next number. Never edit an applied
migration — someone's database already ran it. When another branch is open,
the next number may already be taken there:
[branching.md](branching.md), "Migration numbers". Verify the new one applies to an
**existing** database, not just a fresh one:

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
the same `config.toml` every other credential and the MTGO handle live in.

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

**Restoring is a documented procedure, not a `--restore` flag** — a flag
cannot make it safe, since the watcher is a separate process this CLI does
not own, holding an open connection plus its own `-wal`/`-shm`:

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

The restored copy sits at whatever `schema_version` it recorded; `project`
applies anything newer, and forward-only migrations mean a backup can be
restored into the same or a newer version of this code — never an older one.

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
  state across polls, restored into the next `Segmenter` before its first
  line (`reader/segmenter.py`'s `carry_state()`/`restore_carry()`); a
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
| Reader | `raw_events`, `ingest_state` | Append-only; never deleted |
| Projector | `decks`, `matches`, `games`, `turns`, `turn_zones`, `card_events`, `deck_guids`, `opponent_archetype`, `game_decks`, `rank_snapshot` | Deleted and recomputed by every `project()` |
| Downloaded reference | `cards`, `archetypes`, `archetype_fetch`, `meta_event`, `meta_fetch`, `meta_fetch_source`, `meta_deck`, `meta_round_match` | Never deleted — a rebuild must not throw away a fetch |
| Metagame classifier | `meta_deck_archetype` | Deleted and recomputed by every `classify_meta_decks()`, same reasoning as `opponent_archetype` |
| The user | `opponent_deck_override` | Never deleted — their own pick for their own match |
| Authored prose | `deck_narrative`, `matchup_brief`, `match_narrative`, `leaks_narrative` | Never deleted by `project()` — written, not derived, so a rebuild could not recompute them |

`cards` (downloaded reference) gained `power`, `toughness` and `keywords` in
`migrations/031_card_body.sql` — printed-body fields the draft assistant's
local card grade needed, fetched from Scryfall by `cards.py --scryfall`
alongside the pre-existing `oracle_text`/`mana_cost`/`type_line`/`rarity`
columns, with the same `COALESCE`-protected upsert those already use.
Nothing reads them since the draft assistant was deleted;
`migrations/048_drop_draft.sql` keeps them as part of the card database and
drops every draft table.

**Authored prose arrives by two paths, not one.** Either a CLI `--import` of an
answer written elsewhere (the prompt/import round trip — `docs/brief.md`), or a
`POST .../narrative` route with a Claude credential configured (`docs/llm.md`).
Both write the same rows; the generated path additionally stamps `model`,
`input_tokens`, `output_tokens` and `cost_usd`, which an imported row leaves
`NULL` rather than `0.0` — zero would claim a fact where there is only an
absence (rule 4).

`deck_narrative` and `matchup_brief` are stamped with the `list_hash` and
`corpus_commit` they were written about, so a stored artifact can report itself
stale rather than silently disagreeing with a changed 75 or a moved corpus.
`match_narrative` and `leaks_narrative` carry a `context_hash` instead, serving
the same purpose against the evidence they were written from.

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
`deck_guids`, `decks` or `rank_snapshot` — and `deck_id` is always `NULL`. So
an MTGO match has no `turns` row at all, not a row of zeros; everything above
this point is Arena-only in practice. `card_events.grp_id` itself needs more
than an exact name match to fill in: MTGO's transcript spells a token as
`"<Base> Token"` and a double-faced/adventure/split card by its front face
alone, both different from Arena's own `cards.name` spelling —
`_resolve_grp_id` tries the exact name, then a token lookup gated on
`type_line LIKE 'Token%'`, then an exact-prefix match against a combined
name, taken only when it identifies exactly one card; an ambiguous or
genuinely unknown name stays `NULL` (rule 4) with a warning, never a guess.
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

## Naming the opponent's deck

Arena never sends the opponent's decklist (see
[arena-log.md](arena-log.md) trap 11b), so it is inferred from the cards they
revealed. `src/sensei_top/archetypes/source.py` downloads rule-based
definitions; `classify.py` evaluates them against what a match showed and
writes `opponent_archetype`. Classification runs immediately after `project()`
in both `cmd_project` and `LiveIngester.poll_once`, because a rebuild deletes
its output — it is part of finishing the rebuild, not a separate job.

Naming a match at all needs its format first — `classify_matches` calls
`match_formats(conn)` once before its loop and skips any match whose verdict
isn't a key in `definitions` (`skipped_format`). For an Arena match that
verdict is `format_key(deck_format, event_id)`, unchanged. An MTGO match
carries neither, so `match_formats` reads its format off both seats' revealed
cards instead (`card_events` joined to `cards`, skipping token rows): a
Standard verdict needs at least five distinct non-token cards, none
`not_legal`, none `banned` as of the match's own date (a card banned *after*
the match was played still counts as legal at the time — "never window
across a ban," the same rule `guide/window.py` enforces elsewhere; a banned
card whose ban no detectable reset dates is never assumed legal), and no card
with unknown legality. This is the only reason an MTGO match can reach
`opponent_archetype`/`v_match_opponent` at all — before this, every MTGO
match verdicted `None` and was always `skipped_format`.

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
`_start_reference_refresh` is a writer by the same argument: its own connection, ticking every five minutes, and its
Arena-card step (`cards.refresh_arena_cards`) only ever inserts the handful
of grpIds an Arena patch actually added, so the write stays short even though
the thread itself never stops. A write that loses to the rebuild's 5.7 s lock
is caught by the loop and retried on the next tick. The daily backup's own background thread (see
"Backups" above) is yet another writer by the same argument, but for a
different reason: its only writes are two tiny `backup_state` upserts before
and after the multi-minute copy, so it is a long *reader*, not a long
*writer* — WAL's one-writer-many-readers guarantee means it never blocks or
delays the watcher at all, no matter how long the `VACUUM INTO` itself takes.

`v_match_opponent` (and `v_matchup_winrate`, unioned across every match named
onto one key) also carry `opponent_colors`: the colours the opponent actually
*revealed* (`v_opponent_cards.colors`), never the archetype's assumed
colours — a classified match can be all colours its definition allows while
the opponent has only shown one. `v_opponent_cards.colors` is `''` both when
only colourless cards were revealed and when revealed cards' colours are
simply unknown (no matching `cards` row yet); those two cannot be told apart,
so `''` becomes `NULL` at this column, and the dashboard renders nothing for
it — never the word "Colourless" (rule 4: unknown means `NULL`, never a
guess). This is what lets `ManaPips` (docs/design-system.md) render the real
disc-and-glyph symbols beside an opponent-deck label instead of a parsed-out
colour prefix.

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

Ban-awareness is inherited from `guide/window.py` rather than reimplemented:
a banned card is dropped from every count and an archetype the reset killed
(`structural_change`'s `"gone"` verdict) is excluded from the prior entirely,
rather than windowing the corpus to post-reset dates alone. Measured, the
ban-aware full corpus scored 90% precision on 6,773 decks against the
windowed corpus's 82% on 655 — a card-to-archetype association is not a win
rate, so the "never window `meta_*` across a ban" rule (which protects rates
and shares) does not forbid this; a banned card simply never appears in a
live match to begin with.

`classify_matches()` builds one prior per run (not per match) and combines
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
`MTGmelee` sources are real Standard constructed results — the same format
`archetypes/` already classifies. `metagame/` fetches it windowed by date and
incremental by blob SHA (the cache is ~157 MB of history this project mostly
does not need); see [metagame.md](metagame.md) for the evidence-tier rules
that constrain what each stored event is allowed to claim, and for why
`archetypes.classify`'s rule engine runs in a different mode against a full
decklist than it does against the dozen cards a live match reveals.
