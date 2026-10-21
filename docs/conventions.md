# Conventions

## Python

Python 3.12+, `uv` for packages, `ruff` for lint (line length 100; `E, F, W, I,
N, UP, B, SIM, RUF`). `from __future__ import annotations` at the top of every
module.

- **Dataclasses for state**, not dicts. `LogEntry` is frozen with slots;
  accumulators (`MatchState`, `GameState`, `LiveStats`) are mutable.
- **`StrEnum` for closed sets** of string constants (`EntryKind`).
- **Module-level constants for magic values** (`WIN`, `LOSS`, `_CHUNK_BYTES`,
  `UNITY_PREFIX`), never inline literals repeated across functions.
- **Leading underscore for module-private helpers** (`_outcome`, `_messages`,
  `_rows`, `_now_iso`).
- **Type hints everywhere**, including return types. `X | None`, not `Optional`.

### Transactions

Every connection that can write uses `isolation_level=None` — `db.py`'s
`connect()` and the API's `get_writable_conn` alike — so sqlite3 never opens an implicit transaction and every write block is explicit:

```python
conn.execute("BEGIN")
try:
    ...
    conn.execute("COMMIT")
except Exception:
    conn.execute("ROLLBACK")
    raise
```

This is not style. Under autocommit, a bare `conn.commit()` is a no-op on a
write that has already landed, so a route writing two tables (the deck guide's
generate route writes `deck_narrative` *and* `matchup_brief`) would commit the
first even when the second raised — and the next request would read the
half-written result as complete rather than retrying.

`PRAGMA foreign_keys=ON` is set on both for the same reason: a
connection that enforces less than the rest of the project is a difference that
surfaces as a corrupted row much later, not as a failing test now.

### Errors degrade, they do not halt

The rule from the brief, applied consistently: an unknown or missing field
produces a warning and a `NULL`, never an exception that stops ingestion.

- `Projector.feed()` catches every exception per event, and inside a GRE
  event per message, counts a warning, and continues. One malformed payload
  must not cost a whole session, and one bad message must not cost the
  messages batched beside it.
- A missing log file is not an error — it returns empty stats.
- A truncated payload is discarded, never emitted half-parsed.
- A failing live poll is recorded; the loop continues.
- Warnings are counted (`projector.warnings`) and surfaced in CLI output, so
  "0 warnings" is a meaningful signal rather than silence.
- A log line never names a player, the user included: no handle, screen
  name or user id, and no raw log line, which carries them. Say which game,
  which card, what count. The log goes into the diagnostics zip, and the
  issue templates ask for that zip on a public issue.

**Never invent a value to fill a gap.** If self seat is unresolved, `turns`
rows are omitted entirely rather than written with meaningless self/opponent
columns. `NULL` means "not observed" and must keep meaning that.

## Comments and docstrings

The house style is heavier on *why* than most codebases, and deliberately so:
this project decodes an undocumented format that changes without notice. It is
run by agents, not human maintainers, and an agent carries no memory from one
session to the next. A comment at the trap site is what keeps the next session
from finding the same trap the hard way.

That reasoning is also why prose costs something here. Every session re-reads
whatever it opens, so a paragraph copied from a doc gets paid for on every
read, and the copy drifts away from the original until one of them is wrong.
One fact, one place:

1. **A trap or a contract lives at the code. A design explanation lives in
   `docs/`.** A trap is a constraint the code can't show: why `inode` is
   `TEXT` (overlayfs overflows SQLite's INTEGER), why `executescript()` is
   avoided, why both line endings are accepted. A contract is what a caller
   may rely on: what a function returns when the data is missing, which
   field paths it reads, and the client version they were checked against.
   A module docstring that explains a design is a pointer to the doc section,
   plus the traps the doc can't hold.
2. **Never copy a measured number.** A timing, a size or a count belongs to
   the doc that measured it. Cite that doc, or leave the number out.
3. **Point at code by symbol, never by line number** (`live.py::project_if_due`,
   not `live.py:589`), and never at a plan's section ("brief §5"). Line
   numbers move with every edit, and the plans aren't in the repo.
4. **No history at the code.** What a function used to do, which plan
   changed it and what was tried first belong in git and `docs/status.md`.
   A comment says what is true now.
5. **Say a thing once per file.** When two functions share a trap, explain
   it at the first one and point to it from the second.

Two scripts enforce part of this: `scripts/check_prose.py` fails on a plan
label or a line number, and `scripts/check_doc_refs.py` on a path or symbol
a comment names that no longer exists. Whether a comment copies a doc or a
measured number is the reviewer's to catch.

Two more, as before:

- **Never comment what the next line does**, and never leave notes addressed to
  a reviewer ("fixed the bug where…"). Comments are for the next reader.
- **No decorative section-banner comments in `src/`** (`# --- like this ---`).
  Function and class boundaries already mark sections, and the
  `navigating-sensei-top` skill's `repo_map.py` gives a symbol-level map on
  demand. A banner adds token cost on every read without adding
  information. Tests are the exception: a test file is a long run of
  same-shaped functions, and `docs/testing.md` groups them under these
  comments.

When you discover a trap, write the comment that would have saved you.

### Reviewing prose

When you review a comment or docstring, sort each paragraph into one of six
classes. The first two stay. The other four get fixed.

| Class | What it is | What to do |
|---|---|---|
| trap | a constraint the code can't show | keep it at the code |
| contract | what a caller may rely on | keep it at the code |
| duplicate | restates a doc section, or another paragraph in the same file | replace it with a pointer to the original. If the doc doesn't actually hold the fact, move it to the doc first |
| history | what used to be true, or how the code got here | delete it, after checking that git or `docs/status.md` holds it |
| restates | says what the next lines do | delete it |
| stale | no longer matches the code | fix it to match. If a doc says the same thing, find out which one is right before changing either |

## CLI

`argparse` with subcommands, each wired via `set_defaults(func=cmd_x)`.

- Shared option groups are factored into a helper (`_add_watch_arguments`)
  rather than repeated per subcommand.
- User errors exit with a message that says what to run next:
  `sys.exit(f"No database at {path}. Run 'sensei-top ingest' then 'project'.")`
- Defaults are safe: loopback binding, `data/sensei-top.db`, read-only `serve`, and
  every request passes `api/guard.py`'s loopback check.
- Output is plain text, aligned columns, with an explicit empty state
  (`"(no completed matches yet)"`) rather than printing nothing.
- **Every sentence the API sends a user goes through `_()` or
  `ngettext()`** (`sensei_top/i18n.py`), with the English text as the
  msgid and named placeholders filled after the lookup. A prompt never
  does: its builder runs under `i18n.english()`. Log lines and CLI output
  are English and never wrapped. The rules and the traps are in
  [i18n.md](i18n.md).

## API

FastAPI, built by `create_app(db_path, watcher=None)`.

- **Metric endpoints are thin `SELECT`s over views**, and aggregation a `SELECT`
  can express belongs in the view, not the handler. Endpoints that serve a
  feature package's own analysis (`review/`, `guide/`, `table/`, `coach/`) call
  that package instead and convert its dataclasses — see "Aggregation: views
  versus Python" in [architecture.md](architecture.md).
- **Pydantic response models are the contract.** They drive the OpenAPI schema,
  which generates the frontend's types — so field names here are the frontend's
  field names, and `Field(description=...)` explains units (`player-turns, not
  rounds`).
- **Prose fields are written in the request's language.** The
  middleware in `api/app.py` reads `Accept-Language` and every `_()` the
  route reaches answers in it; the server stores no language. A field the
  dashboard turns into its own sentence is a code, not prose (a `kind`,
  a `status`), and the dashboard keys the words.
- **Read-only, enforced**: every connection sets `PRAGMA query_only=ON`, except
  `get_writable_conn`, used only by rule 6's authored-artifact routes.
- **Check the path before connecting.** `sqlite3.connect()` *creates* a missing
  file; an empty database renders identically to "no games played yet", hiding
  a wrong `--db`. Missing means 503 with the fix in the message.
- **Dependencies live at module scope**, reading state off `request.app.state`.
  A dependency defined inside `create_app` is an unresolvable forward reference
  to pydantic under `from __future__ import annotations` — this was a real
  failure, not a hypothetical.
- One connection per request, closed in a `finally`.
- **A loopback bind isn't enough on its own.** `api/guard.py`'s
  `LoopbackGuard` sits outermost on the app and refuses, in order: a `Host`
  that doesn't name loopback (DNS rebinding), a foreign `Origin` or
  cross-site fetch metadata (a page this app didn't serve), and — for
  anything but `GET`/`HEAD` — a request missing the dashboard's own
  `X-Tracker-Client` header (the backstop for a browser that sends neither
  `Origin` nor fetch metadata: a page can't add a custom header cross-origin
  without a CORS preflight, and this app never answers one). Swagger's
  `/docs` "Try it out" is same-origin, so it clears Host/Origin/fetch-metadata,
  but a PUT/POST there still needs that header added by hand or it 403s like
  any other caller.

## Naming

- Tables and columns: `snake_case`, plural table names (`matches`, `games`).
- Views are prefixed `v_`.
- Migrations: `NNN_short_name.sql`.
- Booleans read as claims: `truncation_detected`, `project_enabled`, `on_play`.
- Timestamps are ISO-8601. Database-generated ones are UTC with `Z`; header
  timestamps from the log are naive local time, and `None` when unknown.

## Dependencies

Prefer the standard library. Every dependency added so far earns its place:
`fastapi`/`uvicorn` for the API, `pydantic` for the schema contract, `orjson`
for parsing the log's payloads, `polib` for the API's translation catalogues,
`keyring` for keys kept in the system keyring, and `anthropic` for the opt-in
call in `llm/client.py`; for development, `pytest` and `ruff`, `httpx2` for
FastAPI's `TestClient`, and `pyinstaller` for the frozen server. Log tailing
is a plain polling loop on purpose — `watchdog` misbehaves on the virtiofs and network mounts this log may live on,
and two seconds of latency is irrelevant for a dashboard.

Keep pins current rather than frozen; the project targets latest stable.
