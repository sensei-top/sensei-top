"""Stage 2: project MTGO's deck files into ``decks``.

Reads the ``raw_events`` rows ``reader/mtgo_decks.py`` stored
(``source = 'mtgo_deck'``, one row per distinct file content) and writes one
``decks`` row per distinct maindeck. The design — the two kinds of file, how
an MTGO row differs from an Arena one, and why ``matches.deck_id`` stays
``NULL`` — is docs/architecture.md, "What a turn snapshot holds". In two
halves, like ``project.py``: ``read_mtgo_decks`` parses before
``projector/matches.py::project()`` opens its transaction, and
``write_mtgo_decks`` inserts inside it, so there is no ``BEGIN``/``COMMIT``
here.

This is the one place that reads a deck file's contents; the reader moved the
bytes and knows nothing of XML or card names.

Two kinds of row
----------------
The reader's label says which kind a row holds, from the file's name:

* ``MtgoDeckFile``, a ``.dek`` the user exported. Every card is a ``Cards``
  element with a ``Name``, a ``Quantity`` and ``Sideboard``.
* ``MtgoDeckGrouping``, a ``grouping *.xml`` from MTGO's own deck store. The
  root is ``CardGrouping``; every card is an ``Item`` with a ``CatId``, a
  ``Quantity`` and ``IsSideboard``, and **no name**. Only
  ``GroupingType="Deck"`` with a ``FormatCode`` that
  ``mtgo/formats.py::FORMAT_CODES`` maps to one of the seven formats is a
  deck; the rest (a binder, a wishlist, a Commander deck) are counted once
  at INFO level, never warned about, since the user keeps those on purpose.

Identity
--------
See ``mtgo_deck_identity`` for the hashed text. The ``mtgo-deck:`` prefix
means it can never equal the text an Arena id hashes, which starts ``[[``.
Names, never ``grp_id``s, so a list with a card Arena lacks still gets a
stable id; and names rather than ``CatId`` values, because one card carries
a different ``CatId`` per printing and swapping a printing is not a
different deck, and because a ``.txt`` export of the same list would carry
names only. The sideboard stays out for the reason
``projector/matches.py::deck_identity`` gives: a list resaved with another
sideboard is the same deck.

``mtgo_card`` holds Scryfall's name, ``Front // Back`` for a card with two
faces, and a ``.dek`` writes the front face only. So a grouping's card is
named by the text before the first `` // ``. A split card has never been
seen in an export, so whether MTGO writes its full name is not known; until
it is, a split card in a grouping and the same card in a ``.dek`` would be
two spellings of one deck.

A ``CatId`` that ``mtgo_card`` lacks has no name to hash. It enters the
identity as ``[CatId <number>]`` (``_UnmappedCatId``), a text no card's name
starts with, so two lists that differ only in such a card stay two decks, as
two ``.dek`` lists that differ only in a card Arena lacks do. When a later
``cards --scryfall`` maps that ``CatId``, the deck's id changes, which orphans
a pick made on the old one; there is no id to keep stable without a name.

One row per distinct maindeck
-----------------------------
The newest row holding a maindeck (by ``logged_at``, then ``id``) supplies
its sideboard; ``name`` and ``format`` are each the newest such row's that
carries one. A ``.dek``'s name is the file's stem (Arena's "most recent name"
rule) and it carries no format; a grouping's name is its ``Name`` attribute
and its format the mapped ``FormatCode``, so a grouping's format can pre-fill
the user's pick. A grouping with no ``Name`` (never seen) carries no name.
``first_seen`` and ``last_seen`` are the earliest and latest ``logged_at``
over every row that holds the maindeck: the file's mtime, as local-clock text
in the shape Arena's timestamps have, so the columns compare as text. A
grouping's own ``Timestamp`` is not read.

``cards_json``
--------------
``{"maindeck": [...], "sideboard": [...], "unresolved": {"maindeck": n,
"sideboard": n}}``. The two lists are ``grp_id``, one entry per copy and
sorted, the shape Arena's rows have. A card is resolved by
``project.py::_resolve_grp_id``, the same rule that gives MTGO
``card_events`` their ``grp_id``, so the two agree. A card that does not
resolve is **left out** of its list with a warning, never given a made-up id
(rule 4), once per rebuild however many decks hold it (``_Resolver``). Only
boards that are written are resolved, so an older version's sideboard cannot
raise a warning about a card that goes nowhere.

``unresolved`` counts the copies left out, per board, on every MTGO row,
``0`` included: ``v_deck_land_count.unresolved_count`` reads
``unresolved.maindeck``.

A file that is not a readable deck
----------------------------------
Warned about by file name and skipped whole, because a list with an entry
missing would get a wrong identity, so there is no partial deck. Unreadable
means: not base64 or not XML, a root other than the kind's own (``Deck`` for a
``.dek``, ``CardGrouping`` for a grouping), a card with no name (a ``Cards``
element that is a direct child of the root with no ``Name``) or no ``CatId``
(an ``Item``, likewise, whose ``CatId`` is not a positive whole number), a
``Quantity`` that is not a positive integer of at most ``_MAX_QUANTITY``, a
board flag (``Sideboard``, ``IsSideboard``) other than the literal ``true`` or
``false``, or no maindeck card. A grouping is checked for being a deck in one
of the seven formats before its cards are read, so a binder's items are never
judged.

The quantity ceiling is not a game rule. ``cards_json`` holds one entry per
copy, so an absurd count would be an out-of-memory error that halts the whole
rebuild, which rule 4 forbids; it sits far above the largest count in the
three sample files.

A half-written file (``reader/mtgo_decks.py`` stores what it saw) is one of
these, and its warning repeats on every rebuild; the finished file is a row
of its own that projects normally.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePath

from sensei_top.mtgo.formats import FORMAT_CODES
from sensei_top.projector.mtgo.project import _resolve_grp_id, _Warner

log = logging.getLogger(__name__)

_IDENTITY_PREFIX = "mtgo-deck:"
_MAX_QUANTITY = 1000
# reader/mtgo_decks.py's label for a deck-store grouping; every other
# mtgo_deck row is a .dek export.
_GROUPING_LABEL = "MtgoDeckGrouping"
_FACE_SEPARATOR = " // "


class _UnreadableDeckError(ValueError):
    """A payload that cannot be read as a whole deck. The message says why."""


class _UnmappedCatId(str):
    """A grouping's card whose ``CatId`` ``mtgo_card`` lacks, standing in for
    its name as ``[CatId <number>]``. A ``str``, so it sorts and hashes into
    the identity like a name; its own type, so resolving it skips the name
    lookup and warns about the ``CatId`` instead."""

    cat_id: int

    def __new__(cls, cat_id: int) -> _UnmappedCatId:
        key = super().__new__(cls, f"[CatId {cat_id}]")
        key.cat_id = cat_id
        return key


@dataclass
class _Parsed:
    """One readable deck payload of either kind. ``name`` and ``format`` are
    ``None`` when the payload carries none."""

    maindeck: Counter[str]
    sideboard: Counter[str]
    name: str | None
    format: str | None


@dataclass
class _Deck:
    """Every ``mtgo_deck`` row that holds one maindeck, folded into one deck.
    ``newest`` is the ``(logged_at, id)`` of the row that supplied
    ``sideboard``, a missing ``logged_at`` sorting as the oldest;
    ``name_from`` and ``format_from`` are the same key for the row that
    supplied ``name`` and ``format``, ``None`` while no row has carried one.
    ``logged`` is the ``logged_at`` of every row that holds it, the missing
    ones left out."""

    maindeck: Mapping[str, int]
    sideboard: Mapping[str, int]
    newest: tuple[str, int]
    logged: list[str]
    name: str | None = None
    name_from: tuple[str, int] | None = None
    format: str | None = None
    format_from: tuple[str, int] | None = None

    def take(self, parsed: _Parsed, key: tuple[str, int], logged: list[str]) -> None:
        """Fold in another row holding this maindeck."""
        self.logged.extend(logged)
        if key > self.newest:
            self.sideboard, self.newest = parsed.sideboard, key
        if parsed.name is not None and (self.name_from is None or key > self.name_from):
            self.name, self.name_from = parsed.name, key
        if parsed.format is not None and (self.format_from is None or key > self.format_from):
            self.format, self.format_from = parsed.format, key


class _Resolver:
    """Card lookups for one pass: ``CatId`` -> name through ``mtgo_card``,
    name -> ``grp_id`` through ``_resolve_grp_id``. Both are cached for the
    whole pass, and a card that does not resolve warns once, whichever deck
    asks first."""

    def __init__(self, conn: sqlite3.Connection, warner: _Warner) -> None:
        self._conn = conn
        self._warner = warner
        self._names: dict[int, str | None] = {}
        self._grp_ids: dict[str, int | None] = {}

    def card_key(self, cat_id: int) -> str:
        """The name a grouping's ``CatId`` is counted under: ``mtgo_card``'s
        name up to its first `` // ``, or an ``_UnmappedCatId``. Never warns;
        a warning waits for the card to be written (``grp_id``)."""
        if cat_id not in self._names:
            row = self._conn.execute(
                "SELECT name FROM mtgo_card WHERE mtgo_id = ?", (cat_id,)
            ).fetchone()
            self._names[cat_id] = None if row is None else row[0]
        name = self._names[cat_id]
        if name is None:
            return _UnmappedCatId(cat_id)
        return name.split(_FACE_SEPARATOR, 1)[0]

    def grp_id(self, key: str) -> int | None:
        if not isinstance(key, _UnmappedCatId):
            return _resolve_grp_id(self._conn, self._grp_ids, key, self._warner)
        if key not in self._grp_ids:
            self._grp_ids[key] = None
            self._warner.warn(
                f"MTGO CatId {key.cat_id} is not in mtgo_card, left out of every deck "
                "that holds it (sensei-top cards --scryfall fills mtgo_card)"
            )
        return None


def mtgo_deck_identity(maindeck: Mapping[str, int]) -> str:
    """The ``deck_id`` of a maindeck given as ``{card name: total quantity}``.

    sha256 over ``mtgo-deck:`` and the compact JSON of the ``[name, quantity]``
    pairs sorted by name. This text is a stored contract, not an
    implementation detail: a deck pick made later keeps this id across
    rebuilds, so changing the text orphans every pick.
    """
    canonical = _IDENTITY_PREFIX + json.dumps(sorted(maindeck.items()), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _positive_int(text: str | None, ceiling: int | None = None) -> int | None:
    """``text`` as a whole number, or ``None`` unless it is ASCII digits worth
    at least ``1`` and at most ``ceiling``. ``int()`` alone would also take a
    sign, spaces, underscores and non-ASCII digits."""
    if text is None or not (text.isascii() and text.isdigit()):
        return None
    try:
        value = int(text)
    except ValueError:  # more digits than int() converts
        return None
    if value < 1 or (ceiling is not None and value > ceiling):
        return None
    return value


def _quantity(text: str | None) -> int | None:
    """``text`` as a copy count, from ``1`` to ``_MAX_QUANTITY``."""
    return _positive_int(text, _MAX_QUANTITY)


def _xml_root(data: bytes, tag: str) -> ET.Element:
    """The root element of ``data``, which must be ``tag``.

    The standard library's parser, never a regex: names are XML-escaped
    (``Grafdigger&apos;s Cage``). A declared encoding Python does not know
    raises ``LookupError``, and a multi-byte one expat does not support
    (``shift_jis``, ``utf-32``) raises ``ValueError``, rather than
    ``ParseError``, so all three are caught.
    """
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, LookupError, ValueError) as exc:
        raise _UnreadableDeckError(f"not XML ({exc})") from exc
    if root.tag != tag:
        raise _UnreadableDeckError(f"the root element is {root.tag!r}, not {tag!r}")
    return root


def _boards() -> dict[str, Counter[str]]:
    """An empty board per value a board flag may take: maindeck, sideboard."""
    return {"false": Counter(), "true": Counter()}


def _maindeck(boards: dict[str, Counter[str]]) -> Counter[str]:
    if not boards["false"]:
        raise _UnreadableDeckError("it has no maindeck card")
    return boards["false"]


def _parse_deck(data: bytes, source_file: str) -> _Parsed:
    """The bytes of one ``.dek`` file, as ``{card name: total quantity}`` per
    board, named by ``source_file``'s stem. Quantities are summed per name
    within a board, since two printings of a card are two ``Cards`` lines.
    Raises ``_UnreadableDeckError`` for anything the module docstring lists as
    unreadable."""
    root = _xml_root(data, "Deck")
    boards = _boards()
    for card in root.findall("Cards"):
        name = card.get("Name")
        if name is None or not name.strip():
            raise _UnreadableDeckError("a Cards element has no Name")
        quantity = _quantity(card.get("Quantity"))
        if quantity is None:
            raise _UnreadableDeckError(
                f"{name!r} has Quantity {card.get('Quantity')!r}, "
                f"not a whole number from 1 to {_MAX_QUANTITY}"
            )
        sideboard = card.get("Sideboard")
        if sideboard not in boards:
            raise _UnreadableDeckError(f"{name!r} has Sideboard {sideboard!r}, not true or false")
        boards[sideboard][name] += quantity
    return _Parsed(_maindeck(boards), boards["true"], PurePath(source_file).stem, None)


def _parse_grouping(data: bytes, resolver: _Resolver) -> _Parsed | None:
    """The bytes of one deck-store grouping, as ``_parse_deck`` returns them,
    or ``None`` for a grouping that is not a deck in one of the seven formats.
    Quantities are summed per name within a board, so two printings of a card
    (two ``Item``s) are one card. Raises ``_UnreadableDeckError`` for anything
    the module docstring lists as unreadable."""
    root = _xml_root(data, "CardGrouping")
    if root.get("GroupingType") != "Deck":
        return None
    format_ = FORMAT_CODES.get(root.get("FormatCode") or "")
    if format_ is None:
        return None

    boards = _boards()
    for item in root.findall("Item"):
        cat_id = _positive_int(item.get("CatId"))
        if cat_id is None:
            raise _UnreadableDeckError(
                f"an Item has CatId {item.get('CatId')!r}, not a positive whole number"
            )
        quantity = _quantity(item.get("Quantity"))
        if quantity is None:
            raise _UnreadableDeckError(
                f"CatId {cat_id} has Quantity {item.get('Quantity')!r}, "
                f"not a whole number from 1 to {_MAX_QUANTITY}"
            )
        sideboard = item.get("IsSideboard")
        if sideboard not in boards:
            raise _UnreadableDeckError(
                f"CatId {cat_id} has IsSideboard {sideboard!r}, not true or false"
            )
        boards[sideboard][resolver.card_key(cat_id)] += quantity

    name = root.get("Name")
    if name is not None and not name.strip():
        name = None
    return _Parsed(_maindeck(boards), boards["true"], name, format_)


def _decode(payload: str) -> bytes:
    """A ``raw_events`` payload, which is base64, as the file's bytes."""
    try:
        return base64.b64decode(payload)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise _UnreadableDeckError("the payload is not base64") from exc


def _board(
    resolver: _Resolver, cards: Mapping[str, int]
) -> tuple[list[int], int]:
    """One ``grp_id`` per copy of every card in ``cards`` that resolves,
    sorted, and the number of copies that did not. A card that does not
    resolve is left out; the warning is ``_Resolver.grp_id``'s."""
    grp_ids: list[int] = []
    unresolved = 0
    for name in sorted(cards):
        grp_id = resolver.grp_id(name)
        if grp_id is None:
            unresolved += cards[name]
        else:
            grp_ids.extend([grp_id] * cards[name])
    return sorted(grp_ids), unresolved


@dataclass
class MtgoDeckRows:
    """Every ``decks`` row ``write_mtgo_decks`` inserts, built by
    ``read_mtgo_decks`` before the rebuild takes the write lock."""

    decks: list[tuple]
    warnings: int
    groupings_skipped: int


def project_mtgo_decks(conn: sqlite3.Connection) -> dict[str, int]:
    """Project every ``mtgo_deck`` row in ``raw_events`` into ``decks``:
    ``read_mtgo_decks`` then ``write_mtgo_decks``. Runs inside the caller's
    transaction and writes nothing else. Returns ``{"decks": rows written,
    "warnings": warnings raised, "groupings_skipped": grouping files with no
    row that is a deck in one of the seven formats}``; ``project()`` calls
    the two halves itself, the read before its transaction opens, and adds
    the first two to its own counts."""
    return write_mtgo_decks(conn, read_mtgo_decks(conn))


def write_mtgo_decks(conn: sqlite3.Connection, rows: MtgoDeckRows) -> dict[str, int]:
    """Insert what ``read_mtgo_decks`` built, inside the caller's
    transaction; it reads nothing, so the write lock is held for the inserts
    alone."""
    conn.executemany(
        """
        INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen)
             VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows.decks,
    )
    return {
        "decks": len(rows.decks),
        "warnings": rows.warnings,
        "groupings_skipped": rows.groupings_skipped,
    }


def read_mtgo_decks(conn: sqlite3.Connection) -> MtgoDeckRows:
    """Read and parse every ``mtgo_deck`` row into the ``decks`` rows
    ``write_mtgo_decks`` inserts. Writes nothing: ``project()`` runs it
    before ``BEGIN``, so parsing every stored deck file never holds the
    write lock the live watcher's ingest thread waits on."""
    warner = _Warner()
    resolver = _Resolver(conn, warner)
    decks: dict[str, _Deck] = {}
    skipped: set[str] = set()
    kept: set[str] = set()

    for row in conn.execute(
        "SELECT id, source_file, logged_at, label, payload FROM raw_events "
        "WHERE source = 'mtgo_deck' ORDER BY id"
    ):
        grouping = row["label"] == _GROUPING_LABEL
        kind = "deck-store grouping" if grouping else "deck file"
        try:
            data = _decode(row["payload"])
            parsed = (
                _parse_grouping(data, resolver) if grouping
                else _parse_deck(data, row["source_file"])
            )
        except _UnreadableDeckError as exc:
            warner.warn(
                f"{kind} {row['source_file']!r} (raw_events id {row['id']}) "
                f"is not a readable deck, skipped: {exc}"
            )
            continue
        if parsed is None:
            skipped.add(row["source_file"])
            continue
        if grouping:
            kept.add(row["source_file"])

        logged_at = row["logged_at"]
        key = (logged_at or "", row["id"])
        logged = [] if logged_at is None else [logged_at]
        deck_id = mtgo_deck_identity(parsed.maindeck)
        deck = decks.get(deck_id)
        if deck is None:
            deck = decks[deck_id] = _Deck(parsed.maindeck, parsed.sideboard, key, [])
        deck.take(parsed, key, logged)

    rows: list[tuple] = []
    for deck_id, deck in decks.items():
        maindeck, maindeck_unresolved = _board(resolver, deck.maindeck)
        sideboard, sideboard_unresolved = _board(resolver, deck.sideboard)
        cards = {
            "maindeck": maindeck,
            "sideboard": sideboard,
            "unresolved": {"maindeck": maindeck_unresolved, "sideboard": sideboard_unresolved},
        }
        rows.append(
            (
                deck_id, deck.name, deck.format, json.dumps(cards),
                min(deck.logged, default=None), max(deck.logged, default=None),
            )
        )

    groupings_skipped = len(skipped - kept)
    if groupings_skipped:
        log.info(
            "[mtgo] %d deck-store grouping file(s) skipped: a binder, a wishlist or a deck "
            "outside the seven formats",
            groupings_skipped,
        )
    return MtgoDeckRows(rows, warner.count, groupings_skipped)
