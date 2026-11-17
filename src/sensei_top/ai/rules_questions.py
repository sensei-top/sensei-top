"""The rules questions a feature asks the hosted coach, written from card rows
by fixed templates, with no model (``docs/llm.md``, "Rules notes").

Everything here is a pure function of card rows except the four ``for_*``
builders, which read the same objects the feature's own prompt reads (never
a second definition of "the deck's 75" or of "the opponent's staples").

Traps:

- A regenerate must ask the same questions, or the cache (``rules_notes``)
  never hits: the builders rank by count then name, and the selection
  has no randomness.
- ``EVERGREEN`` is the keywords a 30-question trial (2026-11-16) graded borderline or worse, not a
  rules source.
- A hook is a text heuristic: a card with no oracle text has none.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from sensei_top.ai.coach.evidence import build_coach_evidence
from sensei_top.ai.guide.narrative import _opponent_sections
from sensei_top.guide.bundle import build_deck_guide
from sensei_top.guide.rcq import build_rcq
from sensei_top.i18n import english
from sensei_top.review.snapshot import build_snapshot

MAX_QUESTIONS = 4
MAX_USES = 2

T1 = "T1"
T2 = "T2"
T3 = "T3"

EVERGREEN = frozenset({
    "flying", "haste", "vigilance", "trample", "reach", "deathtouch", "lifelink",
    "first strike", "double strike", "menace", "defender", "flash", "hexproof",
    "indestructible", "ward", "protection", "enchant", "equip", "kicker",
    "transform", "scry", "surveil", "mill", "fight", "cycling", "convoke", "prowess",
})

_CARD_TYPES = (
    "artifact", "battle", "creature", "enchantment", "instant", "land", "planeswalker",
    "sorcery",
)
# "counter" is a verb only before its object; "+1/+1 counter" is a noun.
_VERBS = (
    r"(?:target|destroy|exile|counter(?=\s+(?:target|up to|all|each|any))|return|"
    r"sacrifice|damage to)"
)
_SENTENCE_BREAK = re.compile(r"[.\n\u2022]")
_REMINDER = re.compile(r"\([^)]*\)")
_SELF = re.compile(
    r"\bthis (?:artifact|battle|creature|enchantment|land|planeswalker|spell|card|permanent)\b",
    re.IGNORECASE,
)
_NOT_THEIRS = re.compile(r"\byou control\b|\bfrom your (?:graveyard|hand)\b")
_ANY_TARGET = re.compile(
    r"\bdamage to (?:any(?: other)? target|each of up to \w+ other targets)", re.IGNORECASE
)
_DAMAGEABLE = {"creature", "planeswalker", "battle"}


@dataclass(frozen=True, slots=True)
class CardRow:
    name: str
    type_line: str | None = None
    oracle_text: str | None = None
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RulesQuestion:
    question: str
    template: str
    cards: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeatureCards:
    """Cards in rank order, best first: ``mine`` the player's, ``theirs`` the
    opponent's."""

    mine: tuple[CardRow, ...]
    theirs: tuple[CardRow, ...]


def front(name: str) -> str:
    """The name a question uses: an ``A // B`` card's front face."""
    return name.split(" // ")[0]


def _types_and_subtypes(card: CardRow) -> tuple[set[str], set[str]]:
    line = front(card.type_line or "").lower()
    left, _, right = line.partition("—")
    types = {t for t in left.split() if t in _CARD_TYPES}
    return types, set(right.split())


def _kinds(card: CardRow) -> set[str]:
    types, _subtypes = _types_and_subtypes(card)
    if not types:
        return set()
    kinds = set(types)
    if "land" not in types:
        kinds.add("spell")
    if not types & {"instant", "sorcery"}:
        kinds.add("permanent")
    return kinds


def _own_text(card: CardRow) -> str:
    text = card.oracle_text or ""
    for name in sorted({card.name, front(card.name)}, key=len, reverse=True):
        text = text.replace(name, "")
    return _SELF.sub("", _REMINDER.sub("", text))


def _kind_pattern(kinds) -> str:
    forms = [k[:-1] + "(?:y|ies)" if k.endswith("y") else k + "s?" for k in sorted(kinds)]
    return rf"\b(?:{'|'.join(forms)})\b"


def _targets(y: CardRow, x: CardRow) -> bool:
    """Y's text reaches X's kind: a verb, then the kind in the same sentence,
    unless the clause is about Y's own side (``another ...``, ``... you
    control``, ``... from your graveyard``)."""
    kinds = _kinds(x)
    types = _types_and_subtypes(x)[0]
    if not kinds:
        return False
    # "noncreature spell" names every spell but a creature's; blank every
    # non<type> run (and its noun) for X's own types: "nonland, nontoken permanent".
    text = re.sub(
        rf"\bnon(?:{'|'.join(sorted(types))})\b(?:,?\s+non\w+)*(?:,?\s+\w+)?", "",
        _own_text(y),
    )
    if types & _DAMAGEABLE and _ANY_TARGET.search(text):
        return True
    verbs = re.compile(rf"\b{_VERBS}\b", re.IGNORECASE)
    kind = re.compile(_kind_pattern(kinds), re.IGNORECASE)
    for sentence in _SENTENCE_BREAK.split(text):
        for verb in verbs.finditer(sentence):
            rest = sentence[verb.end():]
            for hit in kind.finditer(rest):
                if re.search(r"\banother\b", rest[: hit.start()], re.IGNORECASE):
                    continue
                tail = re.split(r"[,:;]", rest[hit.end():], maxsplit=1)[0]
                if _NOT_THEIRS.search(tail):
                    continue
                return True
    return False


def _names(y: CardRow, x: CardRow) -> bool:
    """Y's text names one of X's subtypes or keywords; a keyword Y carries
    itself is not a mention of X's."""
    text = _own_text(y).lower()
    _types, subtypes = _types_and_subtypes(x)
    own = {k.lower() for k in y.keywords}
    words = subtypes | ({k.lower() for k in x.keywords} - own)
    return any(re.search(rf"\b{re.escape(w)}s?\b", text) for w in words)


def has_hook(a: CardRow, b: CardRow) -> bool:
    """One of the two cards' text reaches the other's kind, either way. A
    card with no text has no hook, and so is no pair for one."""
    if not a.oracle_text or not b.oracle_text:
        return False
    return _targets(a, b) or _targets(b, a) or _names(a, b) or _names(b, a)


def _is_instant_speed(card: CardRow) -> bool:
    types, _subtypes = _types_and_subtypes(card)
    return "instant" in types or "flash" in {k.lower() for k in card.keywords}


def _is_land(card: CardRow) -> bool:
    return "land" in _types_and_subtypes(card)[0]


def _t2_keyword(card: CardRow) -> str | None:
    for keyword in sorted(card.keywords, key=str.lower):
        if keyword.lower() not in EVERGREEN:
            return keyword.lower()
    return None


def _pairs(mine: Sequence[CardRow], theirs: Sequence[CardRow]):
    order = sorted(
        ((i, j) for i in range(len(mine)) for j in range(len(theirs))),
        key=lambda ij: (ij[0] + ij[1], ij[0]),
    )
    return [(mine[i], theirs[j]) for i, j in order]


def build_questions(
    mine: Sequence[CardRow], theirs: Sequence[CardRow]
) -> list[RulesQuestion]:
    """Up to ``MAX_QUESTIONS``, the same list for the same input: two T1,
    one T3, one T2, a slot left empty filled from what remains in that order,
    no card in more than ``MAX_USES`` questions. ``mine`` and ``theirs`` are
    in rank order; with no ``theirs`` (the coach report) only T2 is asked."""
    candidates: dict[str, list[RulesQuestion]] = {T1: [], T2: [], T3: []}
    for m, t in _pairs(mine, theirs):
        if has_hook(m, t):
            candidates[T1].append(RulesQuestion(
                f"How does {front(m.name)} interact with {front(t.name)}?", T1,
                (m.name, t.name),
            ))
        if _is_instant_speed(t) and not _is_land(m):
            candidates[T3].append(RulesQuestion(
                f"What happens if my opponent casts {front(t.name)} in response to "
                f"{front(m.name)}?", T3, (m.name, t.name),
            ))
    for m in mine:
        keyword = _t2_keyword(m)
        if keyword is not None:
            candidates[T2].append(RulesQuestion(
                f"How does {keyword} work on {front(m.name)}?", T2, (m.name,),
            ))

    chosen: list[RulesQuestion] = []
    uses: Counter = Counter()

    def take(template: str, limit: int) -> None:
        for q in candidates[template]:
            if limit == 0 or len(chosen) == MAX_QUESTIONS:
                return
            if q in chosen or any(uses[c] >= MAX_USES for c in q.cards):
                continue
            chosen.append(q)
            uses.update(q.cards)
            limit -= 1

    take(T1, 2)
    take(T3, 1)
    take(T2, 1)
    for template in (T1, T3, T2):
        take(template, MAX_QUESTIONS)
    return chosen


def card_from_row(row: sqlite3.Row) -> CardRow:
    try:
        keywords = tuple(json.loads(row["keywords"] or "[]"))
    except (TypeError, ValueError):
        keywords = ()
    return CardRow(row["name"], row["type_line"], row["oracle_text"], keywords)


def _rows(
    conn: sqlite3.Connection, *, grp_ids: Sequence[int] = (), names: Sequence[str] = ()
) -> list[sqlite3.Row]:
    out: list[sqlite3.Row] = []
    for column, values in (("grp_id", sorted(set(grp_ids))), ("name", sorted(set(names)))):
        if values:
            out.extend(conn.execute(
                "SELECT grp_id, name, type_line, oracle_text, keywords FROM cards "
                f"WHERE {column} IN ({','.join('?' * len(values))}) "
                "ORDER BY oracle_text IS NULL, grp_id",
                values,
            ))
    return out


def _ranked(
    rows: Sequence[sqlite3.Row], weight: dict, key: str
) -> tuple[CardRow, ...]:
    """One card per name, the heaviest first (the weights of a name's printings
    added), ties by name. A name keeps the row with oracle text, which
    ``_rows`` sorts first."""
    seen: dict[str, sqlite3.Row] = {}
    total: Counter = Counter()
    counted: set = set()
    for row in rows:
        seen.setdefault(row["name"], row)
        if (row["name"], row[key]) not in counted:
            counted.add((row["name"], row[key]))
            total[row["name"]] += weight.get(row[key], 0)
    ordered = sorted(seen.values(), key=lambda r: (-total[r["name"]], r["name"]))
    return tuple(card_from_row(r) for r in ordered)


def _by_grp(conn: sqlite3.Connection, grp_ids: Sequence[int]) -> tuple[CardRow, ...]:
    counts = Counter(grp_ids)
    return _ranked(_rows(conn, grp_ids=grp_ids), counts, "grp_id")


@english()
def for_match(conn: sqlite3.Connection, match_id: str) -> FeatureCards:
    """The cards each side resolved in the match, most resolves first, the
    plays ``review/narrative.py::play_lines_of`` lists."""
    snap = build_snapshot(conn, match_id)

    def resolved(plays) -> list[int]:
        return [p.grp_id for p in plays if p.category == "Resolve" and p.grp_id is not None]

    return FeatureCards(
        _by_grp(conn, resolved(snap.self_plays)), _by_grp(conn, resolved(snap.opponent_plays))
    )


def _staples(
    conn: sqlite3.Connection, guide, own_ids: Sequence[int], *, own_name, own_key, extra=()
) -> tuple[CardRow, ...]:
    """The opponent staples the guide prompt shows, read through
    ``_opponent_sections``' ``staples_out``; highest share first, then most
    copies, then name. A card the player's own 75 holds is left out, as the
    prompt leaves its oracle text out."""
    out: list = []
    _opponent_sections(
        [], guide, conn=conn, own_name=own_name, own_key=own_key,
        shown_grp_ids=set(own_ids), extra=extra, staples_out=out,
    )
    best: dict[int, tuple[float, float]] = {}
    for card, _archetype_key, share in out:
        if card.grp_id is not None and card.grp_id not in own_ids:
            best[card.grp_id] = max(best.get(card.grp_id, (0, 0)), (share, card.copies))
    seen: dict[str, tuple[tuple[float, float], sqlite3.Row]] = {}
    for row in _rows(conn, grp_ids=list(best)):
        if row["name"] not in seen or best[row["grp_id"]] > seen[row["name"]][0]:
            seen[row["name"]] = (best[row["grp_id"]], row)
    ordered = sorted(seen.values(), key=lambda v: (-v[0][0], -v[0][1], v[1]["name"]))
    return tuple(card_from_row(row) for _rank, row in ordered)


@english()
def guide_cards(conn: sqlite3.Connection, guide) -> FeatureCards:
    """The deck's 75 by copies, and the staples of the archetypes its prompt
    shows, from a ``DeckGuide`` already built."""
    cards = guide.provenance.deck.current_cards
    own_ids = [*(cards.get("maindeck") or []), *(cards.get("sideboard") or [])]
    diff = guide.list_diff
    return FeatureCards(
        _by_grp(conn, own_ids),
        _staples(
            conn, guide, own_ids,
            own_name=diff.archetype_name if diff is not None else None,
            own_key=diff.archetype_key if diff is not None else None,
        ),
    )


@english()
def for_guide(conn: sqlite3.Connection, key: str, *, report_cache=None) -> FeatureCards | None:
    """``guide_cards`` for the deck ``key``; ``None`` for an unknown deck."""
    guide = build_deck_guide(conn, key, report_cache=report_cache)
    return None if guide is None else guide_cards(conn, guide)


@english()
def for_rcq(
    conn: sqlite3.Connection, key: str, decklist: str, *,
    expected: Sequence[str] = (), own: str | None = None, report_cache=None,
) -> FeatureCards | None:
    """The pasted 75 by copies, and the staples of the archetypes the RCQ
    prompt shows, the expected ones included. ``None`` for an unknown deck."""
    evidence = build_rcq(
        conn, key, decklist, list(expected), own, report_cache=report_cache
    )
    if evidence is None:
        return None
    own_ids = [*evidence.resolved.main_grp_ids, *evidence.resolved.side_grp_ids]
    return FeatureCards(
        _by_grp(conn, own_ids),
        _staples(
            conn, evidence.guide, own_ids,
            own_name=evidence.own_verdict_name, own_key=evidence.own_verdict_key,
            extra=tuple((x.key, f"-- {x.name} --") for x in evidence.expected),
        ),
    )


def coach_cards(conn: sqlite3.Connection, decklists) -> FeatureCards:
    """The kept decks' cards by copies across them (``DeckList``s), names
    only; the coach report has no opponent cards."""
    counts: Counter = Counter()
    for deck in decklists:
        for count, name in (*deck.main, *deck.side):
            counts[name] += count
    return FeatureCards(_ranked(_rows(conn, names=list(counts)), counts, "name"), ())


@english()
def for_coach(
    conn: sqlite3.Connection, fmt: str, *, report_cache=None
) -> FeatureCards | None:
    """``None`` when the evidence is too thin for a report."""
    evidence = build_coach_evidence(conn, fmt=fmt, source="all", report_cache=report_cache)
    if evidence is None:
        return None
    return coach_cards(conn, evidence.decklists)
