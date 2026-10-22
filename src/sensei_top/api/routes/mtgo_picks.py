"""Picking the deck for many MTGO matches at once — docs/architecture.md,
"Who owns which table".

``GET /api/mtgo/picks/candidates`` ranks every waiting MTGO match against the
user's lists and groups them at request time (``mtgo/picks.py`` decides who
belongs together; this module loads, decorates and converts). Nothing is
stored and nothing is written by the reads: the user still confirms, a group
at a time, through ``PUT /api/mtgo/picks``, which writes ``mtgo_match_pick``
only and all-or-nothing.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException

from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.matches import (
    MtgoPickGroups,
    MtgoPickHints,
    MtgoPicksIn,
    MtgoPicksWritten,
)
from sensei_top.api.routes.matches import (
    _card_names,
    _format_prefill,
    _last_pick_formats,
    _match_source,
    _mtgo_decks,
    _pick_problem,
    _upsert_mtgo_pick,
)
from sensei_top.archetypes import build_prior
from sensei_top.archetypes.classify import (
    card_colors_by_name,
    classify_seen,
    load_definitions,
    played_colors_by_name,
    played_colors_of,
)
from sensei_top.i18n import _
from sensei_top.mtgo.picks import Group, PickList, PickMatch, Unsure, group_matches

router = APIRouter()

_MISSING_CARDS = 8


class _Hints:
    """The archetype the engine reads from a match's user-side cards, with the
    definitions, colours and per-format prior loaded once, on first use."""

    def __init__(self, conn: sqlite3.Connection, all_names: set[str]) -> None:
        self._conn = conn
        self._all_names = all_names
        self._caches: dict[str, Any] = {}
        self._priors: dict[str, Any] = {}

    def of(self, names: list[str], fmt: str | None) -> str | None:
        if fmt is None or not names:
            return None
        if not self._caches:
            self._caches["definitions"] = load_definitions(self._conn)
            self._caches["colors"] = card_colors_by_name(self._conn)
            self._caches["played"] = played_colors_by_name(self._conn, self._all_names)
        if fmt not in self._priors:
            self._priors[fmt] = build_prior(self._conn, fmt)
        colors, cards_seen = played_colors_of(self._caches["played"], names)
        verdict = classify_seen(
            names, colors, cards_seen, fmt=fmt, definitions=self._caches["definitions"],
            colors_by_name=self._caches["colors"], prior=self._priors[fmt],
        )
        return verdict.label if verdict is not None else None


@dataclass
class _State:
    rows: list[sqlite3.Row]
    mtgo_matches: int
    info: dict[str, sqlite3.Row]
    played: dict[str, set[int]]
    decks: dict[str, Any]
    cards_of: dict[str, Any]
    held: dict[str, frozenset[int]]
    result: Any
    card_rows: dict[int, sqlite3.Row]

    def names_of(self, grp_ids: set[int]) -> list[str]:
        # Tokens are not the user's cards; the single route's overlap counts
        # them, but a hint or a "missing" line naming one would mislead.
        return sorted({
            self.card_rows[g]["name"] for g in grp_ids
            if g in self.card_rows
            and "Token" not in (self.card_rows[g]["type_line"] or "").split("—")[0]
        })


@router.get("/api/mtgo/picks/candidates", response_model=MtgoPickGroups, tags=["matches"])
def mtgo_picks_candidates(conn: Conn) -> dict[str, Any]:
    """Every MTGO match still waiting for a deck, grouped by the list it fits.

    A match is ranked by the distinct cards its user played that each list
    holds, among the lists in its inferred format and those with none (all
    lists when no format is inferred). Under 5 cards, under half of them in
    the best list, or no list in its format: ``unsure``. Otherwise it joins
    the group of its top list(s): ``sure`` at 90 % or more, ``partial``
    below; a tie at the top is a group with nothing proposed. Lists within 2
    cards of the top show as ``close_in``. Hints live on
    ``/api/mtgo/picks/hints``. Nothing is written, and no pick is inferred:
    the user confirms.
    """
    # One read transaction, so a rebuild committing between the SELECTs below
    # cannot hand the match list and the played sets different snapshots.
    conn.execute("BEGIN")
    try:
        return _build(conn)
    finally:
        conn.execute("COMMIT")


@router.get("/api/mtgo/picks/hints", response_model=MtgoPickHints, tags=["matches"])
def mtgo_picks_hints(conn: Conn) -> dict[str, Any]:
    """The archetype the engine reads from the user's own played cards, for
    partial groups (by group key) and unsure matches (by match id) only.
    Slower than the groups (the corpus prior), so the page asks for it in
    its own request once the groups have drawn; never stored."""
    conn.execute("BEGIN")
    try:
        return _hints(conn)
    finally:
        conn.execute("COMMIT")


@router.put("/api/mtgo/picks", response_model=MtgoPicksWritten, tags=["matches"])
def set_mtgo_picks(body: MtgoPicksIn, conn: WritableConn) -> dict[str, int]:
    """Confirm the deck and format of many MTGO matches at once. Every item
    gets the single pick's checks first; the first failure answers 400 and
    nothing is written. The writes are the single pick's upsert, in one
    transaction."""
    deck_ids = {deck["deck_id"] for deck in _mtgo_decks(conn)}
    seen: set[str] = set()
    for item in body.items:
        mid = item.match_id
        if mid in seen:
            problem = _("Match {id} is listed twice.").format(id=mid)
        else:
            seen.add(mid)
            match = _match_source(conn, mid)
            if match is None:
                problem = _("No match {id}.").format(id=mid)
            else:
                reason = _pick_problem(match, item.deck_id, item.format, deck_ids)
                if reason is None:
                    continue
                problem = {
                    "arena": _(
                        "Match {id} is an Arena match; Arena's log names its deck."
                    ).format(id=mid),
                    "empty": _("Match {id}: pick a deck, a format, or both.").format(id=mid),
                    "unknown_deck": _(
                        "Match {id}: pick a deck from GET /api/mtgo/picks/candidates."
                    ).format(id=mid),
                }[reason]
        raise HTTPException(status_code=400, detail=problem)

    conn.execute("BEGIN")
    try:
        for item in body.items:
            _upsert_mtgo_pick(conn, item.match_id, item.deck_id, item.format)
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"written": len(body.items)}


def _load(conn: sqlite3.Connection) -> _State:
    rows = conn.execute(
        """
        SELECT m.match_id, m.self_seat, m.opponent_name, m.started_at, m.result,
               m.games_won, m.games_lost, i.format AS inferred
          FROM matches m
          JOIN v_match_deck v ON v.match_id = m.match_id
          LEFT JOIN match_format_inference i ON i.match_id = m.match_id
         WHERE m.source = 'mtgo' AND v.deck_confirmed = 0
         ORDER BY m.started_at DESC, m.match_id
        """
    ).fetchall()
    mtgo_matches = conn.execute("SELECT COUNT(*) FROM matches WHERE source = 'mtgo'").fetchone()[0]
    if not rows:
        return _State([], mtgo_matches, {}, {}, {}, {}, {}, None, {})
    info = {r["match_id"]: r for r in rows}

    played: dict[str, set[int]] = {r["match_id"]: set() for r in rows}
    for c in conn.execute(
        """
        SELECT DISTINCT ce.match_id, ce.grp_id
          FROM card_events ce
          JOIN matches m ON m.match_id = ce.match_id AND ce.seat = m.self_seat
          JOIN v_match_deck v ON v.match_id = m.match_id
         WHERE m.source = 'mtgo' AND v.deck_confirmed = 0 AND ce.grp_id IS NOT NULL
        """
    ):
        played[c["match_id"]].add(c["grp_id"])

    decks = {d["deck_id"]: d for d in _mtgo_decks(conn)}
    cards_of = {i: json.loads(d["cards_json"]) for i, d in decks.items()}
    held = {
        i: frozenset(c.get("maindeck", [])) | frozenset(c.get("sideboard", []))
        for i, c in cards_of.items()
    }
    result = group_matches(
        [
            PickMatch(r["match_id"], frozenset(played[r["match_id"]]), r["inferred"],
                      r["started_at"])
            for r in rows
        ],
        [PickList(i, d["format"], held[i]) for i, d in decks.items()],
    )

    every_played = set().union(*played.values())
    card_rows = {
        r["grp_id"]: r
        for r in conn.execute(
            f"SELECT grp_id, name, type_line FROM cards WHERE grp_id IN "
            f"({','.join('?' * len(every_played))})",
            list(every_played),
        )
    } if every_played else {}

    return _State(rows, mtgo_matches, info, played, decks, cards_of, held, result, card_rows)


def _hints(conn: sqlite3.Connection) -> dict[str, Any]:
    state = _load(conn)
    if not state.rows:
        return {"groups": {}, "unsure": {}}
    every_name = set(state.names_of(set().union(*state.played.values())))
    hints = _Hints(conn, every_name)

    def user_hint(match_id: str) -> str | None:
        return hints.of(
            state.names_of(state.played[match_id]), state.info[match_id]["inferred"]
        )

    groups: dict[str, str | None] = {}
    for group in state.result.groups:
        if group.fit != "partial":
            continue
        labels = Counter(h for p in group.matches if (h := user_hint(p.match_id)))
        groups[group.key] = labels.most_common(1)[0][0] if labels else None
    return {"groups": groups, "unsure": {u.match_id: user_hint(u.match_id)
                                         for u in state.result.unsure}}


def _build(conn: sqlite3.Connection) -> dict[str, Any]:
    state = _load(conn)
    rows, info, played, decks = state.rows, state.info, state.played, state.decks
    cards_of, held, result = state.cards_of, state.held, state.result
    mtgo_matches, names_of = state.mtgo_matches, state.names_of
    if not rows:
        return {"waiting": 0, "mtgo_matches": mtgo_matches, "groups": [], "unsure": []}

    prefill = _last_pick_formats(conn)
    def match_out(
        match_id: str, cards_seen: int, scores: dict[str, int] | None
    ) -> dict[str, Any]:
        r = info[match_id]
        out = {
            "match_id": match_id, "started_at": r["started_at"],
            "opponent_name": r["opponent_name"], "result": r["result"],
            "games_won": r["games_won"], "games_lost": r["games_lost"],
            "cards_seen": cards_seen,
        }
        if scores is not None:
            out["scores"] = scores
        return out

    def group_out(group: Group) -> dict[str, Any]:
        ids = group.matches
        group_played: set[int] = set().union(*(played[p.match_id] for p in ids))
        inferred = Counter(
            info[p.match_id]["inferred"] for p in ids if info[p.match_id]["inferred"]
        )
        common = inferred.most_common(1)[0][0] if inferred else None
        close = sorted(
            group.close_in, key=lambda d: (-group.close_in[d], decks[d]["name"] or "", d)
        )
        lists = []
        for deck_id in [*group.top, *close]:
            deck = decks[deck_id]
            fill, source = _format_prefill(deck, prefill, common)
            lacking: Counter[str] = Counter()
            for p in ids:
                lacking.update(names_of(played[p.match_id] - held[deck_id]))
            lists.append({
                "deck_id": deck_id, "name": deck["name"], "top": deck_id in group.top,
                "close_in": group.close_in.get(deck_id, 0),
                "format_prefill": fill, "format_prefill_source": source,
                "card_names": _card_names(conn, cards_of[deck_id], group_played),
                "missing": [
                    {"name": n, "matches": k}
                    for n, k in sorted(lacking.items(), key=lambda kv: (-kv[1], kv[0]))[
                        :_MISSING_CARDS
                    ]
                ],
            })
        # Every listed list, even one the format filter kept out of a match's
        # own ranking: the page shows the fit of whichever the user picks.
        matches = [
            match_out(p.match_id, p.cards_seen,
                      {e["deck_id"]: len(played[p.match_id] & held[e["deck_id"]])
                       for e in lists})
            for p in ids
        ]
        matches.sort(key=lambda m: (m["started_at"] or "", m["match_id"]), reverse=True)
        starts = [m["started_at"] for m in matches if m["started_at"]]
        return {
            "key": group.key, "fit": group.fit,
            "proposed": group.top[0] if len(group.top) == 1 else None,
            "lists": lists, "matches": matches,
            "first_started": min(starts, default=None), "last_started": max(starts, default=None),
        }

    groups = [group_out(g) for g in result.groups]
    groups.sort(
        key=lambda g: (g["fit"] != "sure", -len(g["matches"]), g["lists"][0]["name"] or "")
    )

    def unsure_out(u: Unsure) -> dict[str, Any]:
        best = None
        if u.best is not None:
            best = {"deck_id": u.best[0], "name": decks[u.best[0]]["name"],
                    "cards_matched": u.best[1]}
        return {
            **match_out(u.match_id, u.cards_seen, None), "reason": u.reason, "best": best,
            "format": info[u.match_id]["inferred"],
        }

    unsure = [unsure_out(u) for u in result.unsure]
    return {"waiting": len(rows), "mtgo_matches": mtgo_matches, "groups": groups, "unsure": unsure}
