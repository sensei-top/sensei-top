"""A pasted decklist: the 75 a player is about to register, read from the
text Arena's export, MTGO's export or a hand-typed list gives.

Two steps, kept apart on purpose. ``parse_decklist`` reads text into counts
by name and knows nothing about the card database; ``resolve_names`` maps
those names to ``grp_id``s. A name that does not resolve stays a name: it is
listed in ``ResolvedList.unresolved`` and never fuzzy-matched to a near
spelling (AGENTS.md non-negotiable #4) — a guess here would put the wrong
card's oracle text in front of the reader.

Anything odd about the list (a short maindeck, a long sideboard, a fifth
copy, a line that is not a card) is a warning, never an error: the player
may be registering exactly that, and the guide is still worth writing.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass

from sensei_top.i18n import _, ngettext

MAINDECK_MIN = 60
SIDEBOARD_MAX = 15
MAX_COPIES = 4
BASIC_LANDS = frozenset({
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest", "snow-covered wastes",
})

_MAIN_HEADERS = frozenset({"deck", "maindeck", "main deck", "main", "mainboard"})
_SIDE_HEADERS = frozenset({"sideboard", "side", "side board"})
_COMPANION_HEADERS = frozenset({"companion"})
_CARD_LINE = re.compile(r"^(?P<sb>SB:\s*)?(?P<n>\d+)\s*[xX]?\s+(?P<name>.+?)\s*$")
# An Arena export's "(SET) 123" printing suffix: an upper-case set code in
# parentheses, then the collector number.
_ARENA_PRINTING = re.compile(r"\s+\([A-Z0-9]{2,6}\)(?:\s+\S+)?$")


@dataclass(frozen=True, slots=True)
class ParsedList:
    main: Counter
    side: Counter
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedList:
    main_grp_ids: list[int]
    side_grp_ids: list[int]
    unresolved: tuple[str, ...]


def parse_decklist(text: str) -> ParsedList:
    """Read an Arena export (``Deck``/``Sideboard``/``Companion`` headers,
    ``4 Name (SET) 123``), an MTGO export or a plain list (``4 Name`` or
    ``4x Name``, a blank line before the sideboard, or ``SB:`` lines).
    A companion goes to the sideboard, as paper rules have it."""
    main: Counter = Counter()
    side: Counter = Counter()
    warnings: list[str] = []
    section = "main"

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            # A blank line after maindeck cards starts the sideboard, the
            # MTGO export's only separator. Before any card (an Arena
            # export's "About" block) it means nothing.
            if section == "main" and main:
                section = "side"
            continue
        lowered = line.casefold().rstrip(":")
        if lowered in _MAIN_HEADERS:
            section = "main"
            continue
        if lowered in _SIDE_HEADERS:
            section = "side"
            continue
        if lowered in _COMPANION_HEADERS:
            section = "companion"
            continue
        if lowered == "about" or lowered.startswith("name "):
            continue

        match = _CARD_LINE.match(line)
        if match is None:
            warnings.append(
                _('Could not read this line, so it was left out: "{line}"').format(line=line)
            )
            continue
        name = _ARENA_PRINTING.sub("", match["name"]).strip()
        count = int(match["n"])
        if not name or count == 0:
            warnings.append(
                _('Could not read this line, so it was left out: "{line}"').format(line=line)
            )
            continue
        if match["sb"] or section in ("side", "companion"):
            side[name] += count
        else:
            main[name] += count

    main_total = sum(main.values())
    side_total = sum(side.values())
    if main_total < MAINDECK_MIN:
        warnings.append(
            ngettext(
                "The maindeck has {n} cards, fewer than {minimum}.",
                "The maindeck has {n} cards, fewer than {minimum}.",
                main_total,
            ).format(n=main_total, minimum=MAINDECK_MIN)
        )
    if side_total > SIDEBOARD_MAX:
        warnings.append(
            ngettext(
                "The sideboard has {n} cards, more than {maximum}.",
                "The sideboard has {n} cards, more than {maximum}.",
                side_total,
            ).format(n=side_total, maximum=SIDEBOARD_MAX)
        )
    for name, n in sorted((main + side).items()):
        if n > MAX_COPIES and name.casefold() not in BASIC_LANDS:
            warnings.append(
                ngettext(
                    "{n} copies of {card} across the maindeck and sideboard, more than "
                    "{maximum}.",
                    "{n} copies of {card} across the maindeck and sideboard, more than "
                    "{maximum}.",
                    n,
                ).format(n=n, card=name, maximum=MAX_COPIES)
            )

    return ParsedList(main=main, side=side, warnings=tuple(warnings))


def _name_index(conn: sqlite3.Connection) -> tuple[dict[str, int], dict[str, int]]:
    """Two case-insensitive lookups, whole name and front face of an
    ``A // B`` name, each to one ``grp_id``: the lowest one carrying oracle
    text, else the lowest."""
    best_whole: dict[str, tuple[bool, int]] = {}
    best_front: dict[str, tuple[bool, int]] = {}

    def offer(table: dict[str, tuple[bool, int]], key: str, rank: tuple[bool, int]) -> None:
        current = table.get(key)
        if current is None or rank < current:
            table[key] = rank

    for row in conn.execute(
        "SELECT grp_id, name, oracle_text IS NULL AS no_text FROM cards WHERE name IS NOT NULL"
    ):
        rank = (bool(row["no_text"]), row["grp_id"])
        name = row["name"]
        offer(best_whole, name.casefold(), rank)
        if " // " in name:
            offer(best_front, name.split(" // ", 1)[0].strip().casefold(), rank)
    return (
        {key: grp_id for key, (_, grp_id) in best_whole.items()},
        {key: grp_id for key, (_, grp_id) in best_front.items()},
    )


def resolve_names(conn: sqlite3.Connection, parsed: ParsedList) -> ResolvedList:
    """Map every parsed name to a ``grp_id``, one entry per copy (the shape
    ``decks.cards_json`` uses). An exact, case-insensitive name first, then
    the front face of a double-faced, split or adventure card, which is how
    an Arena export names one. Anything else is unresolved, never guessed."""
    whole, front = _name_index(conn)
    unresolved: list[str] = []

    def grp_ids(counts: Counter) -> list[int]:
        out: list[int] = []
        for name, n in counts.items():
            key = name.casefold()
            grp_id = whole.get(key, front.get(key))
            if grp_id is None:
                if name not in unresolved:
                    unresolved.append(name)
                continue
            out.extend([grp_id] * n)
        return out

    return ResolvedList(
        main_grp_ids=grp_ids(parsed.main),
        side_grp_ids=grp_ids(parsed.side),
        unresolved=tuple(unresolved),
    )
