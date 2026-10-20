"""Card names: grpId -> "Sleight of Hand".

Everything Arena logs about a card is a number, so the names have to come from
somewhere else. There are two sources, and the local one is preferred:

1. **The installed client's own card database** — a plain SQLite file inside
   the Arena install. No network, always in step with the client that wrote
   the log, and complete: it names tokens, the back faces of double-faced
   cards and alternate-art basics, none of which Scryfall's ``arena_id``
   covers. Re-run ``sensei-top cards`` after an Arena patch, or let ``serve``
   notice on its own (below) — that path is a local file read, not a network
   call, so it needs no button and no credential (non-negotiable #5 governs
   metered/networked calls; this is neither).
2. **Scryfall's bulk export** — the fallback for when Arena is not installed
   on this machine (reading a log copied from elsewhere). It is one of the
   free downloads (docs/llm.md, "The standard for the free downloads"), and
   it only ever downloads: no game data leaves the machine.

``ingest`` and ``project`` never touch this module. ``serve`` runs leg 1
alone, through ``refresh_arena_cards``: ``cli.py::_start_reference_refresh``
calls it on a background thread at startup, then again on any tick of its
loop that finds the client database's path or mtime changed. It imports only
the grpIds this table lacks (the Cube-pack gap, at the end). The Scryfall leg
(2) is the user's own call — ``sensei-top cards --scryfall`` once, and until
they do, rules text and legality stay NULL.

Scryfall's ``default_cards`` export is the right one: it lists every English
printing, and ``arena_id`` (the same number as Arena's ``grpId``) is attached
per printing. ``oracle_cards`` collapses to one printing per card and drops
``arena_id`` for many of them; ``all_cards`` adds every other language for a
tenfold size increase and no extra Arena coverage.

The export is served as gzipped JSONL, one card object per line, so it is
decompressed and parsed a line at a time and never held in memory whole. Only
the Arena-legal minority survives into the ``cards`` table under its
``arena_id``, plus one row per MTGO-only card under a synthetic negative
``grp_id`` = -(its lowest ``mtgo_id``) (``_write_synthetic_cards``); a
positive id is always Arena's. The same pass also keeps every printing's
``mtgo_id`` and name in ``mtgo_card`` (``_mtgo_row``): Magic Online's deck
store names its cards by that number alone, and an MTGO printing need not
have an ``arena_id``.

Name backfill. ``arena_id`` alone leaves a real gap: Arena assigns its *own*
grpId to every alternate-art, showcase or bonus-sheet copy of a card, and to
each face of a double-faced, Adventure, Omen or Room card, but Scryfall's bulk
export attaches ``arena_id`` to only one representative printing per
functional card. Every sibling grpId — real, playable, and already sitting in
the local table from the installed-client import — would have no Standard
legality at all (measured: 1,043 rows across TLA/FIN/OM1/ECL/TDM/DSK/WOE
alone), and the same gap leaves rows with an ``oracle_id`` (filled by a Cube
pack's own ``arena_id`` printing) but no ``oracle_text`` — a Cube pack card is
exactly this shape (measured: 39 of 276 Powered Cube grpIds).
``upsert_cards`` fixes both with a second pass, entirely local: while
streaming the export it also indexes every non-token printing's legality in
each of the seven formats, oracle id, rules text and body fields
(``mana_cost``, ``type_line``, ``power``, ``toughness``, ``keywords``,
``produced_mana``) by *name* (``_index_names``) — the combined top-level
name, each ``card_faces[].name``, and (for a localized/reskinned product like
OM1's Marvel names) ``printed_name`` and each face's ``printed_name`` too:
Arena shows "Verilax the Havenskin", Scryfall's ``printed_name``, not
"Anti-Venom, Horrifying Healer", its ``name``, and Scryfall's own om1 objects
already carry the correct Standard legality under that name, so no
cross-set alias to SPM is needed. A face's own name carries that face's own
rules text/cost/type/body, never the merged top-level card's — the
front-face fallback ``_row`` uses is only for the *combined* name.
``produced_mana``/``keywords`` are whole-card properties with no per-face
form, so every name a card answers to carries the same value for them. After
the ``arena_id`` upsert, any row still NULL is backfilled by exact name match,
COALESCE-only (never overwrites a value a row already has) — except legality,
which the backfill *owns* on the rows it fills and replaces on every run
(below).

A name is skipped **entirely** only when its Standard legality or its
oracle_id resolves to more than one distinct value across the export — that
disagreement is the signal that two different cards share a name. When those
two agree, oracle_id is filled, each of the seven formats' ``card_legality``
rows is filled *independently* (a row is written when every printing that has
a value for that format agrees on it, and none when they disagree), and each
of the other seven fields is then filled *independently*: only when that
field alone resolves to a single value, left NULL — never guessed
(non-negotiable #4) — when it doesn't. A ``keywords`` ordering quirk or a
``type_line`` erratum on one printing must never blank the legality fix this
backfill exists for. Tokens are excluded on both sides: a token printing
never enters the index, and a row whose ``type_line`` says Token is never
filled — Arena's Treasure and Spirit tokens share their names with non-token
Scryfall objects.

Legality is not fill-only, because unlike rules text it changes: a release
date, a ban, a rotation. Fill-only would keep a set's pre-release
``not_legal`` for good once its rows were filled before release, as Reality
Fracture's were: none of its printings carried an ``arena_id`` yet, so the
name backfill was those rows' only source (docs/architecture.md, "Who owns
which table"). So a
resolved name's rows are replaced with the current consensus each run, and a
format the printings now disagree on loses its row rather than keeping a
stale one (rule 4). A grpId the ``arena_id`` write covered in the same run is
never touched: its own printing's answer outranks a name consensus.

Cube packs also lose grpIds outright: some of a Cube's own pack cards exist
only in the installed client's database and never carry Scryfall's
``arena_id`` (measured: 4 of 276 Powered Cube grpIds). ``refresh_arena_cards``
closes that gap without a Scryfall run, by a plain re-import of the client
database's grpIds this table lacks, the way ``serve`` runs it (above).
``arena_cards_missing`` counts the same grpIds without writing; ``serve``
does not call it.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import re
import sqlite3
import time
import urllib.request
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from sensei_top import arena_config, arena_install, steam
from sensei_top.formats import SCRYFALL_KEYS

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data/default-cards"
# Scryfall asks that clients identify themselves and state what they accept,
# and refuses requests that do neither.
HEADERS = {"User-Agent": "sensei-top/0.1", "Accept": "application/json"}
TIMEOUT = 120.0


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


# The download is reported at most once a second, or when it has moved this far.
PROGRESS_INTERVAL = 1.0
PROGRESS_STEP = 0.05


def print_progress(
    stage: str, *, done: int | None = None, total: int | None = None, as_json: bool
) -> None:
    """One progress event on stdout, flushed. `as_json` is `cards --progress`:
    one JSON line the desktop shell parses; otherwise the human line."""
    if as_json:
        event: dict[str, Any] = {"stage": stage}
        if stage == "download":
            event.update(done=done, total=total)
        print(json.dumps({"progress": event}), flush=True)
        return
    if stage == "save":
        print("Saving cards to the database…", flush=True)
        return
    head = "Downloading card data from Scryfall"
    mb = f"{(done or 0) / 1_000_000:.0f}"
    if total is not None:
        print(f"{head}: {mb} of {total / 1_000_000:.0f} MB", flush=True)
    else:
        print(f"{head}: {mb} MB so far", flush=True)


class _CountingReader:
    """Wraps the response and reports the bytes read from it, throttled to one
    event a second or every 5 % of the total. The decompressor reads through
    this, so the count is the wire's, and the last event is the final byte."""

    def __init__(
        self,
        raw: Any,
        total: int | None,
        *,
        as_json: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._raw = raw
        self._total = total
        self._as_json = as_json
        self._clock = clock
        self.done = 0
        self._reported = -1
        self._reported_at = 0.0

    def read(self, size: int = -1) -> bytes:
        # Only `read` is counted: it is the only method GzipFile calls on its fileobj.
        data = self._raw.read(size)
        self.done += len(data)
        self._report(final=not data)
        return data

    def _report(self, *, final: bool = False) -> None:
        if self.done == self._reported:
            return
        now = self._clock()
        moved = (
            self._total is not None
            and self._total > 0
            and (self.done - max(self._reported, 0)) / self._total >= PROGRESS_STEP
        )
        quiet = now - self._reported_at < PROGRESS_INTERVAL
        if self._reported >= 0 and not final and not moved and quiet:
            return
        self._reported = self.done
        self._reported_at = now
        print_progress("download", done=self.done, total=self._total, as_json=self._as_json)


def fetch_default_cards(
    *, as_json: bool = False, clock: Callable[[], float] = time.monotonic
) -> Iterator[dict[str, Any]]:
    """Stream Scryfall's default-cards export. The only networked function.

    Two requests: the bulk-data index names the current file (its URI carries a
    build timestamp, so it cannot be hardcoded), then the file itself, which
    arrives gzipped with one card per line and is yielded as it decompresses.
    Reports the bytes read against the response's Content-Length (else the
    index's compressed_size, else no total) as it goes.
    """
    index = _get_json(BULK_INDEX_URL)
    uri = index.get("jsonl_download_uri")
    if not uri:
        raise RuntimeError(f"Scryfall bulk index named no JSONL export: {index!r}")
    size = index.get("compressed_size")

    request = urllib.request.Request(uri, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        length = response.headers.get("Content-Length")
        total = size if isinstance(size, int) else None
        if length and length.isdigit():
            total = int(length)
        counted = _CountingReader(response, total, as_json=as_json, clock=clock)
        with gzip.GzipFile(fileobj=counted) as stream:  # type: ignore[arg-type]
            for line in stream:
                if stripped := line.strip():
                    yield json.loads(stripped)


def _upper(value: str | None) -> str | None:
    """Both writers store `set_code` uppercase (migrations/041); Scryfall's
    own `set` field is always lowercase."""
    return value.upper() if value else None


def _row(card: dict[str, Any]) -> tuple[Any, ...] | None:
    """One Scryfall printing -> a `cards` row, or None if it has no arena_id
    (paper/MTGO-only — no grpId to join against) or no name (malformed).
    A caller may pass a synthetic negative `arena_id` for an MTGO-only card
    (`_note_mtgo_printing`).

    A double-faced card already carries a combined ``"Front // Back"`` name at
    the top level, but its cost and colors live on the front face only.
    """
    arena_id = card.get("arena_id")
    name = card.get("name")
    if arena_id is None or not name:
        return None
    faces = card.get("card_faces") or [{}]
    front = faces[0] if isinstance(faces[0], dict) else {}
    colors = card.get("colors")
    if colors is None:
        colors = front.get("colors")
    # produced_mana and keywords live only on the top-level card in
    # Scryfall's schema, never per-face (a land's two faces tap for the same
    # mana), so neither has a front-face fallback. Each stays None (not
    # `[]`) when the key is absent, like oracle_text, so the COALESCE in
    # `_insert_cards` can tell "Scryfall says none" from "this row never
    # asked Scryfall".
    produced_mana = card.get("produced_mana")
    # power/toughness: the front-face fallback the returned tuple also gives
    # mana_cost and type_line — a DFC's top-level card carries neither, only
    # its faces do (Delver of Secrets has no top-level "power").
    power = card.get("power") or front.get("power")
    toughness = card.get("toughness") or front.get("toughness")
    keywords = card.get("keywords")
    return (
        arena_id,
        name,
        card.get("mana_cost") or front.get("mana_cost"),
        card.get("type_line") or front.get("type_line"),
        card.get("rarity"),
        _upper(card.get("set")),
        json.dumps(colors or []),
        card.get("oracle_text") or front.get("oracle_text"),
        card.get("oracle_id"),
        json.dumps(produced_mana) if produced_mana is not None else None,
        power,
        toughness,
        json.dumps(keywords) if keywords is not None else None,
    )


_LEGALITY_VALUES = frozenset({"legal", "not_legal", "banned", "restricted"})


def _legalities(card: dict[str, Any]) -> dict[str, str]:
    """The card's legality in each of the seven formats, by MTGO's spelling.
    A format Scryfall omits, or answers with anything outside the four
    values, is left out: unknown, never a guess (rule 4)."""
    given = card.get("legalities") or {}
    return {
        fmt: given[key]
        for fmt, key in SCRYFALL_KEYS.items()
        if given.get(key) in _LEGALITY_VALUES
    }


def _dropped_legalities(card: dict[str, Any]) -> int:
    """How many of the seven formats carry a value `_legalities` refuses."""
    given = card.get("legalities") or {}
    return sum(
        1 for key in SCRYFALL_KEYS.values()
        if given.get(key) is not None and given[key] not in _LEGALITY_VALUES
    )


def _rows(cards: Iterable[dict[str, Any]]) -> Iterator[tuple[Any, ...]]:
    """Keep the Arena-legal printings and flatten each to a row. See `_row`."""
    for card in cards:
        row = _row(card)
        if row is not None:
            yield row


# Objects that are not real, playable cards. They must never seed the name
# backfill (`_index_names`) — an Arena token grp_id often carries a token's own generic
# name ("Food", "Clue", "Ally"), and indexing a token would risk handing that
# name's legality to an unrelated real card that happens to share it (or vice
# versa). Measured: no such collision exists today, but the exclusion is what
# keeps it that way.
_NON_CARD_LAYOUTS = frozenset({"token", "double_faced_token", "emblem", "art_series"})


def _is_non_card(card: dict[str, Any]) -> bool:
    if card.get("layout") in _NON_CARD_LAYOUTS:
        return True
    return "Token" in (card.get("type_line") or "")


# Keeps the per-format keys apart from column names in the name index.
_LEGALITY_PREFIX = "legality:"

# Every column the name backfill can fill, in the order
# `_backfill_by_name`'s UPDATE binds them. `oracle_id`/`produced_mana`/
# `keywords` are whole-card properties; `oracle_text`/`mana_cost`/
# `type_line`/`power`/`toughness` are face-specific — see `_index_names`.
_BACKFILL_FIELDS = (
    "oracle_id", "oracle_text", "produced_mana",
    "power", "toughness", "keywords", "mana_cost", "type_line",
)


def _index_names(
    card: dict[str, Any],
    index: dict[str, dict[str, set[str]]],
) -> None:
    """Record one printing's backfill fields (`_BACKFILL_FIELDS`) and
    per-format legalities (as `legality:<format>`) under every name Arena
    might show it by: the top-level `name`, each `card_faces[].name`, and the
    `printed_name` of both (the module docstring's "Name backfill" says why).

    The legalities, `oracle_id`, `produced_mana` and `keywords` are
    whole-card: every name gets the same value. The other five —
    `oracle_text`, `mana_cost`, `type_line`, `power`, `toughness` — are
    face-specific: a face's own name is indexed under *that face's own*
    value, and only the top-level "Front // Back" name takes the front-face
    fallback (`card.get(x) or front.get(x)`, matching `_row`).

    Tokens, emblems and art-series objects are skipped entirely (`_is_non_card`).
    """
    if _is_non_card(card):
        return

    produced_mana = card.get("produced_mana")
    keywords = card.get("keywords")
    whole_card = {
        # Each format is indexed on its own, so `_backfill_by_name` can fill
        # the formats the printings agree on and leave out the one they don't.
        **{f"{_LEGALITY_PREFIX}{fmt}": value for fmt, value in _legalities(card).items()},
        "oracle_id": card.get("oracle_id"),
        "produced_mana": json.dumps(produced_mana) if produced_mana is not None else None,
        "keywords": json.dumps(keywords) if keywords is not None else None,
    }

    faces = card.get("card_faces") or [{}]
    front = faces[0] if isinstance(faces[0], dict) else {}
    top_values = {
        **whole_card,
        "oracle_text": card.get("oracle_text") or front.get("oracle_text"),
        "mana_cost": card.get("mana_cost") or front.get("mana_cost"),
        "type_line": card.get("type_line") or front.get("type_line"),
        "power": card.get("power") or front.get("power"),
        "toughness": card.get("toughness") or front.get("toughness"),
    }

    def record(name: str | None, values: dict[str, Any]) -> None:
        if not name:
            return
        entry = index[name]
        for field, value in values.items():
            if value is not None:
                entry[field].add(value)

    for key in ("name", "printed_name"):
        record(card.get(key), top_values)

    for face in card.get("card_faces") or []:
        if not isinstance(face, dict):
            continue
        face_values = {
            **whole_card,
            "oracle_text": face.get("oracle_text"),
            "mana_cost": face.get("mana_cost"),
            "type_line": face.get("type_line"),
            "power": face.get("power"),
            "toughness": face.get("toughness"),
        }
        for key in ("name", "printed_name"):
            record(face.get(key), face_values)


def _backfill_by_name(
    conn: sqlite3.Connection,
    index: dict[str, dict[str, set[str]]],
    direct: Iterable[int],
) -> tuple[int, int, int, int, frozenset[str]]:
    """Fill every still-NULL column in `_BACKFILL_FIELDS`, by exact name
    match against the index `_index_names` built. Each column is COALESCE'd
    on its own: a value a row already has is never overwritten, and the
    row's other NULL columns are still filled. Which names are skipped, and
    how each field and format resolves on its own, is the module
    docstring's "Name backfill"; a name whose printings differ only in
    Pauper still gets the other six formats.

    Legality is the one thing this pass replaces rather than fills: every
    non-token row of a resolved name has its rows deleted and rewritten
    from today's consensus, unless its grp_id is in `direct`, the grp_ids
    `upsert_cards` just wrote from their own printing. A name skipped as
    ambiguous keeps whatever rows it has.

    Returns (Standard `card_legality` rows added, legality rows changed or
    removed, oracle_text rows filled, names left ambiguous, the names whose
    `oracle_id` disagrees). That last set is the
    names two different oracle cards answer to; `_write_synthetic_cards` needs
    it so an MTGO-only card is not mistaken for the Arena card that shares its
    name. A name skipped only for its Standard legality is not in it: one
    oracle card is one card, whatever its printings say about Standard.
    """
    updates: list[tuple[str | None, ...]] = []
    legality_by_name: dict[str, dict[str, str]] = {}
    ambiguous = 0
    shared_names: set[str] = set()
    standard_key = f"{_LEGALITY_PREFIX}Standard"
    for name, fields in index.items():
        oracle_split = len(fields.get("oracle_id", ())) > 1
        if oracle_split:
            shared_names.add(name)
        if len(fields.get(standard_key, ())) > 1 or oracle_split:
            ambiguous += 1
            continue
        legality_by_name[name] = {
            key.removeprefix(_LEGALITY_PREFIX): next(iter(values))
            for key, values in fields.items()
            if key.startswith(_LEGALITY_PREFIX) and len(values) == 1
        }
        row = tuple(
            next(iter(values)) if len(values) == 1 else None
            for values in (fields.get(field, set()) for field in _BACKFILL_FIELDS)
        )
        updates.append((*row, name))

    before_legality = conn.execute(
        "SELECT COUNT(*) FROM card_legality WHERE format = 'Standard'"
    ).fetchone()[0]
    before_text = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE oracle_text IS NULL"
    ).fetchone()[0]
    conn.execute("BEGIN")
    try:
        conn.executemany(
            """
            UPDATE cards
               SET oracle_id         = COALESCE(oracle_id, ?),
                   oracle_text       = COALESCE(oracle_text, ?),
                   produced_mana     = COALESCE(produced_mana, ?),
                   power             = COALESCE(power, ?),
                   toughness         = COALESCE(toughness, ?),
                   keywords          = COALESCE(keywords, ?),
                   mana_cost         = COALESCE(mana_cost, ?),
                   type_line         = COALESCE(type_line, ?)
             WHERE name = ?
               -- The index skips token *sources*; this skips token *targets*.
               -- Arena's own token rows share generic names ("Treasure",
               -- "Spirit") with non-token Scryfall objects, and a token
               -- marked not_legal would rule a Standard match out of Standard.
               AND COALESCE(type_line, '') NOT LIKE '%Token%'
            """,
            updates,
        )
        # The seven formats follow the same token-target rule, and replace
        # what a resolved name's rows hold (docstring). Set-based; each
        # format was resolved per name above, so a format the printings
        # disagree on simply has no row here while the others do.
        conn.execute("CREATE TEMP TABLE _direct (grp_id INTEGER PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO _direct VALUES (?)", ((g,) for g in direct))
        conn.execute(
            "CREATE TEMP TABLE _name_legality "
            "(name TEXT NOT NULL, format TEXT NOT NULL, legality TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO _name_legality VALUES (?, ?, ?)",
            [
                (name, fmt, value)
                for name, by_format in legality_by_name.items()
                for fmt, value in by_format.items()
            ],
        )
        conn.execute("CREATE TEMP TABLE _owned (grp_id INTEGER PRIMARY KEY)")
        conn.executemany(
            """
            INSERT OR IGNORE INTO _owned
            SELECT grp_id FROM cards
             WHERE name = ?
               AND COALESCE(type_line, '') NOT LIKE '%Token%'
               AND grp_id NOT IN (SELECT grp_id FROM _direct)
            """,
            [(name,) for name in legality_by_name],
        )
        conn.execute(
            "CREATE TEMP TABLE _old_legality AS SELECT * FROM card_legality "
            "WHERE grp_id IN (SELECT grp_id FROM _owned)"
        )
        conn.execute("DELETE FROM card_legality WHERE grp_id IN (SELECT grp_id FROM _owned)")
        conn.execute(
            """
            INSERT INTO card_legality (grp_id, format, legality)
            SELECT c.grp_id, n.format, n.legality
              FROM cards c JOIN _name_legality n USING (name)
             WHERE c.grp_id IN (SELECT grp_id FROM _owned)
            """
        )
        changed = conn.execute(
            """
            SELECT COUNT(*) FROM _old_legality o
             WHERE NOT EXISTS (SELECT 1 FROM card_legality cl
                                WHERE cl.grp_id = o.grp_id AND cl.format = o.format
                                  AND cl.legality = o.legality)
            """
        ).fetchone()[0]
        for table in ("_direct", "_name_legality", "_owned", "_old_legality"):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    after_legality = conn.execute(
        "SELECT COUNT(*) FROM card_legality WHERE format = 'Standard'"
    ).fetchone()[0]
    after_text = conn.execute(
        "SELECT COUNT(*) FROM cards WHERE oracle_text IS NULL"
    ).fetchone()[0]
    return (
        after_legality - before_legality,
        changed,
        before_text - after_text,
        ambiguous,
        frozenset(shared_names),
    )


def upsert_cards(
    conn: sqlite3.Connection, cards: Iterable[dict[str, Any]], *, progress_json: bool = False
) -> int:
    """Write Scryfall's Arena-legal printings, then backfill sibling grpIds
    that share a name but never got their own arena_id — see the module
    docstring's "Name backfill" section. The same pass also stores every
    printing's `mtgo_id` -> name in `mtgo_card`, Arena-legal or not.

    Prints the save stage once, after the loop and before the first write.
    Returns the number of `cards` rows written, not `mtgo_card`'s.
    """
    primary_rows: list[tuple[Any, ...]] = []
    mtgo_rows: list[tuple[int, str]] = []
    legality_rows: list[tuple[int, str, str]] = []
    dropped = 0
    name_index: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    # Per oracle card, the lowest-mtgo_id printing's finished row and legality,
    # plus the names `_mtgo_row` gave its printings — never the Scryfall object itself,
    # which would hold the export in memory (module docstring).
    lowest_mtgo: dict[str, _SyntheticGroup] = {}
    for card in cards:
        row = _row(card)
        dropped += _dropped_legalities(card)
        if row is not None:
            primary_rows.append(row)
            legality_rows.extend((row[0], fmt, value) for fmt, value in _legalities(card).items())
        if (mtgo_row := _mtgo_row(card)) is not None:
            mtgo_rows.append(mtgo_row)
            if not _is_non_card(card):
                _note_mtgo_printing(lowest_mtgo, card, mtgo_row)
        _index_names(card, name_index)

    print_progress("save", as_json=progress_json)
    written = _write(conn, primary_rows)
    _write_legality(conn, legality_rows)
    mtgo_written = _write_mtgo_cards(conn, mtgo_rows)
    legality_filled, legality_changed, text_filled, ambiguous, shared_names = _backfill_by_name(
        conn, name_index, (row[0] for row in primary_rows)
    )
    synthetic = _write_synthetic_cards(conn, lowest_mtgo.values(), shared_names=shared_names)
    print(
        f"Name backfill: {legality_filled} legality row(s) filled, "
        f"{legality_changed} changed or removed, "
        f"{text_filled} oracle_text row(s) filled, {ambiguous} name(s) left ambiguous"
    )
    print(f"{mtgo_written} MTGO printing(s) stored in mtgo_card")
    print(f"{synthetic} MTGO-only card(s) stored under a negative grp_id")
    print(f"{dropped} legality value(s) outside the four known ones dropped")
    return written


@dataclasses.dataclass(slots=True)
class _SyntheticGroup:
    """What one MTGO-only oracle card needs for its synthetic row: the lowest
    `mtgo_id`'s finished row and legality, the oracle id, and the names
    `_mtgo_row` gave its printings (used to see that an Arena row already
    covers it)."""

    mtgo_id: int | None = None
    row: tuple[Any, ...] | None = None
    legality: dict[str, str] = dataclasses.field(default_factory=dict)
    names: set[str] = dataclasses.field(default_factory=set)
    oracle_id: str | None = None


def _oracle_id_of(card: dict[str, Any]) -> str | None:
    """A reversible printing carries its `oracle_id` on `card_faces[*]`, not at
    the top level; every other layout has it at the top."""
    if card.get("oracle_id"):
        return card["oracle_id"]
    for face in card.get("card_faces") or []:
        if isinstance(face, dict) and face.get("oracle_id"):
            return face["oracle_id"]
    return None


def _note_mtgo_printing(
    groups: dict[str, _SyntheticGroup], card: dict[str, Any], mtgo_row: tuple[int, str]
) -> None:
    mtgo_id, name = mtgo_row
    oracle_id = _oracle_id_of(card)
    group = groups.setdefault(oracle_id or name, _SyntheticGroup())
    group.names.add(name)
    if group.mtgo_id is not None and mtgo_id >= group.mtgo_id:
        return
    row = _row({**card, "arena_id": -mtgo_id, "name": name, "oracle_id": oracle_id})
    if row is None:
        return
    group.mtgo_id, group.row, group.oracle_id = mtgo_id, row, oracle_id
    group.legality = _legalities(card)


def _write_synthetic_cards(
    conn: sqlite3.Connection,
    groups: Iterable[_SyntheticGroup],
    *,
    shared_names: frozenset[str] = frozenset(),
) -> int:
    """Give each MTGO-only card a `cards` row under `grp_id = -(lowest mtgo_id)`.

    A card gets none when a `cards` row carries its `oracle_id`, or a name
    `_mtgo_row` gave one of its printings exists exactly in `cards`. Run it
    after the name backfill, so a client row already carries the `oracle_id`
    the backfill gives it. Every negative row and its `card_legality` is
    deleted and rewritten in one transaction, so a card that has since reached
    Arena loses its row and nothing ever sees the table half-written.
    Legality is `_legalities`', so each row carries its seven formats.

    `shared_names` is `_backfill_by_name`'s set of names whose `oracle_id`
    disagrees across the export: names two different oracle cards answer to.
    A client row under such a name proves nothing about this card. "Careful
    Study" is Odyssey's sorcery, never on Arena, and also a face of an Arena
    card whose own face row carries no `oracle_id`; the name match alone
    would leave the sorcery with no row at all. So a card with an `oracle_id`
    that no `cards` row carries is not skipped for a client row under a
    shared name, and gets its negative row beside the client's. The MTGO
    resolver reads that name as ambiguous and resolves it to neither
    (`projector/mtgo/project.py::_lookup`). A name already taken by another
    negative row in this pass still skips the card, so a name never carries
    two negative rows.
    Returns the rows written.
    """
    conn.execute("BEGIN")
    try:
        conn.execute("DELETE FROM card_legality WHERE grp_id < 0")
        conn.execute("DELETE FROM cards WHERE grp_id < 0")
        names: set[str] = set()
        oracle_ids: set[str] = set()
        for name, oracle_id in conn.execute("SELECT name, oracle_id FROM cards"):
            names.add(name)
            if oracle_id:
                oracle_ids.add(oracle_id)
        claimed: set[str] = set()
        rows: list[tuple[Any, ...]] = []
        legality_rows: list[tuple[int, str, str]] = []
        for group in sorted((g for g in groups if g.row is not None), key=lambda g: g.mtgo_id):
            if group.oracle_id in oracle_ids or group.names & claimed:
                continue
            client_names = group.names & names
            if group.oracle_id is not None:
                client_names -= shared_names
            if client_names:
                continue
            claimed |= group.names
            rows.append(group.row)
            legality_rows.extend((group.row[0], f, v) for f, v in group.legality.items())
        _insert_cards(conn, rows)
        _insert_legality(conn, legality_rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def _mtgo_row(card: dict[str, Any]) -> tuple[int, str] | None:
    """One Scryfall printing -> an `mtgo_card` row, or None if it has no
    `mtgo_id` (most of the export) or no usable name.

    The name is the top-level one, exactly what `_row` stores in `cards.name`:
    a double-faced card is "Front // Back". Unlike `_row` there is no
    `arena_id` condition and no token filter — a `CatId` in a deck grouping is
    looked up here whatever else the printing is.

    One exception: a `reversible_card` (a basic or shock land printed with two
    pictures, a Regent with its Adventure on the back) is named "X // X" at the
    top level, or "Front // Adventure // Front" for the three-part ones.
    Neither spelling is any card's name in Arena's `cards`, and the MTGO
    projector's name -> grp_id rule (exact name, then a front-face prefix)
    cannot resolve it, so such a printing stores `card_faces[0].name` instead,
    the card's own name (measured on the export: face 0 is the card's name on
    all 17 reversible printings that carry an `mtgo_id`). A reversible printing
    with no named first face is skipped, never stored under the unresolvable
    top-level name.
    """
    mtgo_id = card.get("mtgo_id")
    if not isinstance(mtgo_id, int) or isinstance(mtgo_id, bool):
        return None
    name = card.get("name")
    if card.get("layout") == "reversible_card":
        faces = card.get("card_faces") or [{}]
        name = faces[0].get("name") if isinstance(faces[0], dict) else None
    if not name:
        return None
    return mtgo_id, name


def _write_mtgo_cards(conn: sqlite3.Connection, rows: Iterable[tuple[int, str]]) -> int:
    """Store `mtgo_card` rows. Returns the row count given.

    Re-runnable like `_write`: a later import updates a name in place rather
    than duplicating the row. It upserts instead of emptying the table and
    refilling it, because a refill would let an export that carries no
    `mtgo_id` at all (or an empty one) wipe a map that is still right —
    rule 4: missing means "keep what is known", not "forget it".
    """
    rows = list(rows)
    conn.execute("BEGIN")
    try:
        conn.executemany(
            """
            INSERT INTO mtgo_card (mtgo_id, name) VALUES (?, ?)
            ON CONFLICT (mtgo_id) DO UPDATE SET name = excluded.name
            """,
            rows,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


def _insert_legality(conn: sqlite3.Connection, rows: Iterable[tuple[int, str, str]]) -> None:
    """The statement alone: opens no transaction, for a caller that has one."""
    conn.executemany(
        """
        INSERT INTO card_legality (grp_id, format, legality) VALUES (?, ?, ?)
        ON CONFLICT (grp_id, format) DO UPDATE SET legality = excluded.legality
        """,
        list(rows),
    )


def _write_legality(conn: sqlite3.Connection, rows: Iterable[tuple[int, str, str]]) -> None:
    """Store `card_legality` rows (grp_id, format, legality). A later import
    replaces a format's answer: Scryfall's is the current list."""
    conn.execute("BEGIN")
    try:
        _insert_legality(conn, rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _insert_cards(conn: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> None:
    """The statement alone: opens no transaction, for a caller that has one."""
    conn.executemany(
        """
        INSERT INTO cards (grp_id, name, mana_cost, type_line, rarity, set_code, colors,
                           oracle_text, oracle_id, produced_mana,
                           power, toughness, keywords)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (grp_id) DO UPDATE SET
             name = excluded.name,
             mana_cost = excluded.mana_cost,
             type_line = excluded.type_line,
             rarity = excluded.rarity,
             set_code = excluded.set_code,
             colors = excluded.colors,
             oracle_text = COALESCE(excluded.oracle_text, oracle_text),
             oracle_id = COALESCE(excluded.oracle_id, oracle_id),
             produced_mana = COALESCE(excluded.produced_mana, produced_mana),
             power = COALESCE(excluded.power, power),
             toughness = COALESCE(excluded.toughness, toughness),
             keywords = COALESCE(excluded.keywords, keywords),
             updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        """,
        rows,
    )


def _write(conn: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]) -> int:
    """Store card rows, whatever produced them. Returns the row count.

    Re-runnable: a later import refreshes names in place rather than
    duplicating them, so this can be run again whenever a set is released.
    """
    rows = list(rows)
    conn.execute("BEGIN")
    try:
        _insert_cards(conn, rows)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)


# The installed client's own card database: source 1 of the module docstring.
_ARENA_DB_IN_INSTALL = "MTGA_Data/Downloads/Raw/Raw_CardDatabase_*.mtga"
_ARENA_DB_GLOB = f"steamapps/common/MTGA/{_ARENA_DB_IN_INSTALL}"

# Verified against 19,600 cards cross-checked with Scryfall's own rarities.
_RARITY = {1: "basic land", 2: "common", 3: "uncommon", 4: "rare", 5: "mythic"}
# Enums table, type 'CardColor'.
_COLOR = {1: "W", 2: "U", 3: "B", 4: "R", 5: "G"}


def arena_card_database_path() -> Path | None:
    """The installed client's card database, or None if Arena is not installed.

    The filename carries a content hash that changes with every client patch,
    so it is globbed; if a stale copy is left behind, the newest wins.

    The install the log's first line names (``arena_install``) is tried
    first: it is the client that wrote the log, whichever installer put it
    there, on Windows or under Proton. Steam's library folders are the
    fallback, for a log not found or not yet written past its first line.
    """
    install = arena_install.install_dir(arena_config.resolve_log()[0])
    found = list(install.glob(_ARENA_DB_IN_INSTALL)) if install is not None else []
    if not found:
        found = [path for root in steam.library_roots() for path in root.glob(_ARENA_DB_GLOB)]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def _arena_mana_cost(text: str | None) -> str | None:
    """Arena writes mana as ``o5oR``; everything else writes ``{5}{R}``."""
    if not text:
        return None
    return re.sub(r"o([^o]+)", r"{\1}", text)


def _arena_type_line(types: str | None, subtypes: str | None) -> str | None:
    if types and subtypes:
        return f"{types} — {subtypes}"
    return types or subtypes or None


def read_arena_cards(path: Path) -> Iterator[tuple[Any, ...]]:
    """Read grpId -> name (and friends) out of the client's own database.

    Text lives in a localization table keyed by id, in two forms. ``Formatted =
    1`` is the *display* form and embeds Unity rich-text markup: ``<nobr>``
    around every hyphenated name, and a ``<sprite=…>`` badge on Alchemy's
    rebalanced cards. React escapes strings, so those render literally in the
    dashboard, and they match nothing when compared against an outside card
    list. ``Formatted = 0`` is the plain form.

    Exactly the marked-up titles carry a plain twin (1,264 of them), and the
    other 25,308 have only the display form and no markup in it, so preferring
    the plain form loses nothing. Stripping the tags instead would be wrong for
    361 of them: a rebalanced card's plain name is ``A-Cori-Steel Cutter``, and
    deleting the sprite would leave ``Cori-Steel Cutter``, a different card.
    """
    source = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    try:
        for row in source.execute(
            """
            SELECT c.GrpId, c.OldSchoolManaText, c.Rarity, c.Colors, c.ExpansionCode,
                   COALESCE(title_plain.Loc, title.Loc)       AS name,
                   COALESCE(types_plain.Loc, types.Loc)       AS types,
                   COALESCE(subtypes_plain.Loc, subtypes.Loc) AS subtypes
              FROM Cards c
              LEFT JOIN Localizations_enUS title
                ON title.LocId = c.TitleId AND title.Formatted = 1
              LEFT JOIN Localizations_enUS title_plain
                ON title_plain.LocId = c.TitleId AND title_plain.Formatted = 0
              LEFT JOIN Localizations_enUS types
                ON types.LocId = c.TypeTextId AND types.Formatted = 1
              LEFT JOIN Localizations_enUS types_plain
                ON types_plain.LocId = c.TypeTextId AND types_plain.Formatted = 0
              LEFT JOIN Localizations_enUS subtypes
                ON subtypes.LocId = c.SubtypeTextId AND subtypes.Formatted = 1
              LEFT JOIN Localizations_enUS subtypes_plain
                ON subtypes_plain.LocId = c.SubtypeTextId AND subtypes_plain.Formatted = 0
            """
        ):
            if not row["name"]:
                continue
            colors = [
                _COLOR[int(value)]
                for value in (row["Colors"] or "").split(",")
                if value.strip().isdigit() and int(value) in _COLOR
            ]
            yield (
                row["GrpId"],
                row["name"],
                _arena_mana_cost(row["OldSchoolManaText"]),
                _arena_type_line(row["types"], row["subtypes"]),
                _RARITY.get(row["Rarity"]),
                _upper(row["ExpansionCode"]),
                json.dumps(colors),
                # The client's own database carries no rules text,
                # oracle id, mana-production data or body/keywords at all —
                # see migrations/015_card_text.sql,
                # migrations/021_produced_mana.sql and migrations/031_card_body.sql.
                # The COALESCE in `_insert_cards` keeps whatever a prior
                # Scryfall run already supplied rather than erasing it with
                # these Nones.
                None,
                None,
                None,
                None,
                None,
                None,
            )
    finally:
        source.close()


def import_arena_cards(conn: sqlite3.Connection, path: Path) -> int:
    """Copy the installed client's card names into the local table."""
    return _write(conn, read_arena_cards(path))


def _arena_grp_ids(path: Path) -> set[int]:
    """Every grpId the installed client's own database defines — one SELECT
    against that file, nothing else. Kept separate from `read_arena_cards`'
    full join so a mere presence check never pays for the localization
    joins it doesn't need.
    """
    source = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    try:
        return {row[0] for row in source.execute("SELECT GrpId FROM Cards")}
    finally:
        source.close()


def arena_cards_missing(conn: sqlite3.Connection, path: Path) -> int:
    """Count grpIds the installed client's own database defines but this
    table doesn't have a row for yet — a Cube pack card most often (the
    module docstring's Cube-pack gap). Writes nothing. One SELECT against
    the Arena file (`_arena_grp_ids`); the local side is one SELECT on
    `cards` already open on `conn`. `refresh_arena_cards` computes the same
    difference itself rather than calling this.
    """
    existing = {row[0] for row in conn.execute("SELECT grp_id FROM cards")}
    return len(_arena_grp_ids(path) - existing)


def refresh_arena_cards(conn: sqlite3.Connection) -> int | None:
    """Re-import the installed client's card database, but only the grpIds
    this table doesn't have yet — most checks, after the first run, do no
    writing at all. Returns the number of rows imported (0 when nothing was
    missing), or `None` when no Arena install is found on this machine
    (`arena_card_database_path`).

    Unlike `import_arena_cards`, which always rewrites every row the client
    defines (the CLI's own re-run-after-a-patch path, where refreshing
    already-known names is the point), this is meant to be called
    frequently and cheaply from a background thread — see
    `cli.py::_start_reference_refresh` — so it only ever writes the rows
    that are actually new.
    """
    path = arena_card_database_path()
    if path is None:
        return None
    existing = {row[0] for row in conn.execute("SELECT grp_id FROM cards")}
    missing = _arena_grp_ids(path) - existing
    if not missing:
        return 0
    return _write(conn, (row for row in read_arena_cards(path) if row[0] in missing))
