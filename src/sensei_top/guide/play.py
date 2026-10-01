"""The deck's own play evidence — four independent views of one question:
what does this deck actually do across the games it has played?

Each function generalises one table from a one-off script written for a
single deck, scoped to a ``DeckIdentity``'s ``deck_ids`` rather than a
hard-coded deck name.

Two bugs that earlier version of this analysis shipped, and this module
must not reintroduce:

* ``turns.turn_number`` counts player-turns *alternating seats*, so a
  player-turn index is ``(turn_number + 1) // 2``
  (``projector/game_state.py``).
* A "how many games had this card resolve by turn N" bucketing must
  iterate every game, not just games where the card resolved at all, or
  "never resolved" is silently undercounted — this shipped wrong once
  (reported 1-10, the real number was 5-13).
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from sensei_top.guide.deck import DeckIdentity
from sensei_top.review import effects

_TYPE_BUCKETS = (
    "Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Planeswalker", "Land",
)


@dataclass(frozen=True, slots=True)
class BoardCurvePoint:
    """One (result, own-turn) cell of ``board_curve``: the sample size
    behind the medians beside them, per AGENTS.md rule 4 — a median with an
    ``n`` of 1 and a median with an ``n`` of 40 are not the same claim."""

    n: int
    hand: float | None
    life: float | None
    lands: float | None
    opp_permanents: float | None


@dataclass(frozen=True, slots=True)
class ZoneCurveSplit:
    """One card-type-bucket/zone combo's medians, by result and own-turn.
    ``win``/``loss`` default empty rather than being absent — the same
    "empty dict means no data here" convention every ``.get(x, {})`` read
    in ``guide/markdown.py`` already assumes, now made explicit as real
    fields instead of two dynamically-present dict keys."""

    win: dict[str, float]
    loss: dict[str, float]


@dataclass(frozen=True, slots=True)
class WLTally:
    w: int
    l: int  # noqa: E741 -- matches the wire field name `_play_out` already serves


@dataclass(frozen=True, slots=True)
class MulliganBucket:
    games: int
    wins: int
    losses: int


@dataclass(frozen=True, slots=True)
class GameLengthBucket:
    games: int
    median_turns: float | None


def _placeholders(items) -> str:
    return ",".join("?" for _ in items)


def _player_turn(turn_number: int) -> int:
    """A global turn counter alternating seats -> the player's own turn
    index. Turn 1 and 2 are both "your turn 1" if you're on the draw and
    turn_number starts at 1 for whoever goes first; this matches the
    convention the original one-off script verified against a real
    fixture."""
    return (turn_number + 1) // 2


def _game_results(
    conn: sqlite3.Connection, deck_ids: tuple[str, ...]
) -> dict[tuple[str, int], str]:
    if not deck_ids:
        return {}
    return {
        (row["match_id"], row["game_number"]): row["result"]
        for row in conn.execute(
            f"""
            SELECT g.match_id, g.game_number, g.result FROM games g
              JOIN matches m ON m.match_id = g.match_id
             WHERE m.deck_id IN ({_placeholders(deck_ids)}) AND g.result IN ('win', 'loss')
            """,
            deck_ids,
        )
    }


def board_curve(
    conn: sqlite3.Connection, identity: DeckIdentity
) -> dict[str, dict[str, BoardCurvePoint]]:
    """Median hand / life / lands / opponent permanents on the player's
    Nth own turn, split win/loss, with ``n`` (games still live at that
    point) carried per row — the sample size behind each median."""
    if not identity.deck_ids:
        return {}
    rows = list(conn.execute(
        f"""
        SELECT t.match_id, t.game_number, t.turn_number, t.self_life, t.self_hand,
               t.self_lands, t.opp_permanents, g.result
          FROM turns t JOIN matches m ON m.match_id = t.match_id
          JOIN games g ON g.match_id = t.match_id AND g.game_number = t.game_number
         WHERE m.deck_id IN ({_placeholders(identity.deck_ids)}) AND t.active_seat = m.self_seat
         ORDER BY t.match_id, t.game_number, t.turn_number
        """,
        identity.deck_ids,
    ))
    seen: Counter = Counter()
    buckets: dict[str, dict[int, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        key = (row["match_id"], row["game_number"])
        seen[key] += 1
        if row["result"] in ("win", "loss"):
            buckets[row["result"]][seen[key]].append(row)

    def med(rs: list[sqlite3.Row], col: str) -> float | None:
        vals = [r[col] for r in rs if r[col] is not None]
        return round(median(vals), 1) if vals else None

    return {
        result: {
            str(turn_index): BoardCurvePoint(
                n=len(rs),
                hand=med(rs, "self_hand"),
                life=med(rs, "self_life"),
                lands=med(rs, "self_lands"),
                opp_permanents=med(rs, "opp_permanents"),
            )
            for turn_index, rs in sorted(by_turn.items())
        }
        for result, by_turn in buckets.items()
    }


def _type_bucket(type_line: str | None) -> str | None:
    if not type_line:
        return None
    for bucket in _TYPE_BUCKETS:
        if bucket in type_line:
            return bucket
    return None


def zone_curve(
    conn: sqlite3.Connection, identity: DeckIdentity, *, top_n: int = 3
) -> dict[str, ZoneCurveSplit]:
    """Median count of each card-type bucket in each zone on the player's
    Nth own turn, split win/loss — generalises "instants+sorceries in the
    graveyard" (the Izzet Spellementals guide's own mana-discount metric)
    to any deck's own resource curve. Only the buckets whose win/loss
    medians diverge most are returned; every zone/bucket is computed, the
    rest are just not worth a reader's attention.
    """
    if not identity.deck_ids:
        return {}
    results = _game_results(conn, identity.deck_ids)
    # (zone, bucket) -> result -> turn_index -> [counts across games]
    raw: dict[tuple[str, str], dict[str, dict[int, list[int]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    # (match, game, zone, bucket, turn_index) -> count, accumulated per game first
    per_game: dict[tuple, int] = defaultdict(int)
    for row in conn.execute(
        f"""
        SELECT v.match_id, v.game_number, v.turn_number, v.zone, v.type_line
          FROM v_turn_zones v JOIN matches m ON m.match_id = v.match_id
         WHERE m.deck_id IN ({_placeholders(identity.deck_ids)}) AND v.is_self = 1
        """,
        identity.deck_ids,
    ):
        bucket = _type_bucket(row["type_line"])
        if bucket is None:
            continue
        key = (row["match_id"], row["game_number"], row["zone"], bucket, row["turn_number"])
        per_game[key] += 1

    for (match_id, game_number, zone, bucket, turn_number), count in per_game.items():
        result = results.get((match_id, game_number))
        if result is None:
            continue
        turn_index = _player_turn(turn_number)
        raw[(zone, bucket)][result][turn_index].append(count)

    medians: dict[tuple[str, str], dict[str, dict[int, float]]] = {}
    for combo, by_result in raw.items():
        medians[combo] = {
            result: {t: round(median(vals), 1) for t, vals in by_turn.items() if vals}
            for result, by_turn in by_result.items()
        }

    def divergence(combo) -> float:
        win = medians[combo].get("win", {})
        loss = medians[combo].get("loss", {})
        turns = set(win) & set(loss)
        turns = {t for t in turns if 3 <= t <= 10}
        if not turns:
            return 0.0
        diffs = [abs(win[t] - loss[t]) for t in turns]
        return sum(diffs) / len(diffs)

    ranked = sorted(medians, key=divergence, reverse=True)[:top_n]
    return {
        f"{zone}/{bucket}": ZoneCurveSplit(
            win={str(t): v for t, v in medians[(zone, bucket)].get("win", {}).items()},
            loss={str(t): v for t, v in medians[(zone, bucket)].get("loss", {}).items()},
        )
        for zone, bucket in ranked
    }


def _choose_key_cards(
    conn: sqlite3.Connection, identity: DeckIdentity, *, limit: int = 6
) -> list[str]:
    """Maindeck cards at >=3 copies, ranked by is_finisher then mana value —
    the automatic replacement for a hand-kept list of key creatures."""
    maindeck = identity.current_cards.get("maindeck") or []
    counts: Counter = Counter(maindeck)
    grp_ids = [g for g, n in counts.items() if n >= 3]
    if not grp_ids:
        return []
    rows = {
        row["grp_id"]: row
        for row in conn.execute(
            f"SELECT grp_id, name, oracle_text, type_line, mana_cost FROM cards "
            f"WHERE grp_id IN ({_placeholders(grp_ids)})",
            grp_ids,
        )
    }

    def sort_key(grp_id: int):
        row = rows.get(grp_id)
        if row is None:
            return (0, 0)
        finisher = effects.is_finisher(row["oracle_text"], row["type_line"], row["mana_cost"])
        mv = effects.mana_value(row["mana_cost"]) or 0
        return (1 if finisher else 0, mv)

    ranked = sorted(grp_ids, key=sort_key, reverse=True)[:limit]
    return [rows[g]["name"] for g in ranked if g in rows and rows[g]["name"]]


def key_card_timing(
    conn: sqlite3.Connection, identity: DeckIdentity
) -> dict[str, dict[str, WLTally]]:
    """Win rate bucketed by the player-turn a key card first resolved,
    including a "never resolved" bucket — iterated over every game, not
    just games where the card resolved, or that bucket silently undercounts."""
    if not identity.deck_ids:
        return {}
    key_cards = _choose_key_cards(conn, identity)
    if not key_cards:
        return {}

    results = _game_results(conn, identity.deck_ids)
    first: dict[tuple[str, int], dict[str, int]] = defaultdict(dict)
    for row in conn.execute(
        f"""
        SELECT ce.match_id, ce.game_number, ce.turn_number, cd.name
          FROM card_events ce JOIN cards cd ON cd.grp_id = ce.grp_id
          JOIN matches m ON m.match_id = ce.match_id
         WHERE m.deck_id IN ({_placeholders(identity.deck_ids)}) AND ce.seat = m.self_seat
           AND ce.category = 'Resolve' AND cd.name IN ({_placeholders(key_cards)})
         ORDER BY ce.match_id, ce.game_number, ce.turn_number
        """,
        (*identity.deck_ids, *key_cards),
    ):
        first[(row["match_id"], row["game_number"])].setdefault(row["name"], row["turn_number"])

    def bucket(turn: int | None) -> str:
        if turn is None:
            return "never resolved"
        player_turn = _player_turn(turn)
        if player_turn <= 4:
            return "by T4"
        if player_turn <= 6:
            return "T5-6"
        if player_turn <= 8:
            return "T7-8"
        return "T9+"

    out: dict[str, dict[str, WLTally]] = {}
    for card in key_cards:
        tally: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for key, result in results.items():
            tally[bucket(first[key].get(card))][result == "loss"] += 1
        out[card] = {b: WLTally(w=v[0], l=v[1]) for b, v in tally.items()}
    return out


def mulligan_split(
    conn: sqlite3.Connection, where: str, params: Sequence
) -> dict[str, tuple[int, int]]:
    """``(wins, games)`` for games kept at seven vs. mulliganed to six or
    fewer, over a caller-built ``where`` clause on ``games`` (aliased ``g``)
    joined to ``matches`` (aliased ``m``) — the same caller-builds-the-clause
    idiom ``guide/field.py``'s ``_classified_deck_total`` already uses. Both
    keys are always present, even at ``(0, 0)``.

    The one definition of "kept seven vs. mulliganed" that ``mulligan_record``
    below (scoped to one deck identity's ``deck_ids``) and
    ``coach/evidence.py``'s ``_build_mulligans`` (scoped to a report's own
    match population) both call rather than repeat."""
    rows = conn.execute(
        f"""
        SELECT g.self_mulligans, g.result FROM games g
          JOIN matches m ON m.match_id = g.match_id
         WHERE {where} AND g.result IN ('win', 'loss') AND g.self_mulligans IS NOT NULL
        """,
        params,
    ).fetchall()
    kept_seven = [r for r in rows if r["self_mulligans"] == 0]
    mulliganed = [r for r in rows if r["self_mulligans"] > 0]

    def wins_games(rs: list) -> tuple[int, int]:
        return sum(1 for r in rs if r["result"] == "win"), len(rs)

    return {"kept_seven": wins_games(kept_seven), "mulliganed": wins_games(mulliganed)}


def mulligan_record(
    conn: sqlite3.Connection, identity: DeckIdentity
) -> dict[str, MulliganBucket]:
    """Games kept at seven vs. mulliganed to six or fewer, split win/loss —
    the record, never a judgment of any one mulligan. This is a post-game
    read over projected data; the hand actually shipped (after bottoming
    cards under the London rule) is never in the log at any point, so no
    review of a finished game can say whether a mulligan was right — see
    review/analyzers/frame.py's own caveat, and table/opening_hand.py for
    the live pre-decision read this is deliberately not."""
    if not identity.deck_ids:
        return {}
    where = f"m.deck_id IN ({_placeholders(identity.deck_ids)})"
    split = mulligan_split(conn, where, identity.deck_ids)
    return {
        bucket: MulliganBucket(games=games, wins=wins, losses=games - wins)
        for bucket, (wins, games) in split.items()
    }


def game_length(
    conn: sqlite3.Connection, identity: DeckIdentity
) -> dict[str, GameLengthBucket]:
    """Turn count distribution, split win/loss — from v_deck_game_length's
    own precedent, scoped across every deck_id this identity groups."""
    if not identity.deck_ids:
        return {}
    rows = list(conn.execute(
        f"""
        SELECT g.turn_count AS turn_count, g.result AS result
          FROM games g JOIN matches m ON m.match_id = g.match_id
         WHERE m.deck_id IN ({_placeholders(identity.deck_ids)}) AND g.result IN ('win', 'loss')
           AND g.turn_count IS NOT NULL
        """,
        identity.deck_ids,
    ))
    by_result: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        by_result[row["result"]].append(row["turn_count"])
    return {
        result: GameLengthBucket(
            games=len(counts),
            median_turns=round(median(counts), 1) if counts else None,
        )
        for result, counts in by_result.items()
    }
