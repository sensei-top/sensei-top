"""Grouping the MTGO matches that wait for a deck.

Pure: no SQL, no files. The route loads the matches and the lists and
decorates what this returns; this module only decides who belongs with whom.
Nothing here picks a deck for anyone: a group is a proposal the user confirms
with one click (rule 4).

The thresholds were measured on a real history; the rule and that evidence
are in docs/architecture.md, "Picking many MTGO matches at once".
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

MIN_CARDS_SEEN = 5  # below this, a fit says nothing
SURE_FIT = 0.9  # best / cards_seen at or above: "sure"
PARTIAL_FIT = 0.5  # at or above (and below SURE_FIT): "partial"; below: unsure
CLOSE_CARDS = 2  # a list within this many cards of the top is "close"

Reason = Literal["few_cards", "low_fit", "no_list"]


@dataclass(frozen=True)
class PickMatch:
    """A waiting match: the grp_ids its user played, and the format inferred."""

    match_id: str
    played: frozenset[int]
    format: str | None
    started_at: str | None = None


@dataclass(frozen=True)
class PickList:
    """A deck list. ``format`` is the deck store's; ``None`` competes anywhere."""

    deck_id: str
    format: str | None
    held: frozenset[int]


@dataclass(frozen=True)
class Placed:
    """A match grouped under its top list(s)."""

    match_id: str
    cards_seen: int
    top: tuple[str, ...]
    close: tuple[str, ...]
    scores: dict[str, int]  # every competing list


@dataclass(frozen=True)
class Group:
    key: str
    fit: Literal["sure", "partial"]
    top: tuple[str, ...]  # sorted deck ids; more than one is a tie
    close_in: dict[str, int]  # deck id -> matches it was close in
    matches: tuple[Placed, ...]  # in the order the matches were given


@dataclass(frozen=True)
class Unsure:
    match_id: str
    cards_seen: int
    reason: Reason
    # (deck id, cards matched) of the first top list; None when nothing matched
    best: tuple[str, int] | None
    scores: dict[str, int]


@dataclass(frozen=True)
class Grouping:
    groups: tuple[Group, ...]
    unsure: tuple[Unsure, ...]


def group_matches(matches: Iterable[PickMatch], lists: Iterable[PickList]) -> Grouping:
    """Rank every match against the lists in its format and group the sure and
    partial ones by (fit class, tied top lists).

    Lists compete for a match when their format is the match's inferred
    format or is ``None``; a match with no inferred format meets every list.
    Reasons are checked in order: ``few_cards`` (under ``MIN_CARDS_SEEN``),
    ``no_list`` (nothing competes), ``low_fit`` (best under ``PARTIAL_FIT``).
    The bars are compared in integers, ``>=`` at both.
    """
    all_lists = sorted(lists, key=lambda lst: lst.deck_id)
    members: dict[tuple[str, tuple[str, ...]], list[Placed]] = {}
    unsure: list[Unsure] = []
    for match in matches:
        seen = len(match.played)
        competing = [
            lst for lst in all_lists if match.format is None or lst.format in (None, match.format)
        ]
        scores = {lst.deck_id: len(match.played & lst.held) for lst in competing}
        best = max(scores.values(), default=0)
        top = tuple(d for d, s in scores.items() if s == best)
        reason: Reason | None = None
        if seen < MIN_CARDS_SEEN:
            reason = "few_cards"
        elif not competing:
            reason = "no_list"
        elif best * 100 < round(PARTIAL_FIT * 100) * seen:
            reason = "low_fit"
        if reason is not None:
            unsure.append(
                Unsure(
                    match.match_id, seen, reason,
                    (top[0], best) if competing and best > 0 else None, scores,
                )
            )
            continue
        fit = "sure" if best * 100 >= round(SURE_FIT * 100) * seen else "partial"
        close = tuple(d for d, s in scores.items() if d not in top and s >= best - CLOSE_CARDS)
        members.setdefault((fit, top), []).append(
            Placed(match.match_id, seen, top, close, scores)
        )
    groups = []
    for (fit, top), placed in members.items():
        close_in = Counter(d for p in placed for d in p.close)
        groups.append(
            Group(f"{fit}:{'|'.join(top)}", fit, top, dict(close_in), tuple(placed))  # type: ignore[arg-type]
        )
    return Grouping(tuple(groups), tuple(unsure))
