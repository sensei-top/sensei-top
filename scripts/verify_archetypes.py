"""Measure how well the opponent-deck classifier actually does.

Not a unit test and deliberately not in ``tests/``: it needs a real database
with real matches and a downloaded set of definitions, neither of which belongs
in a hermetic suite. Run it before believing any number on the Matchups tab.

The headline is the **self-agreement** check, and it works because of an
asymmetry in what we know. We never see the opponent's decklist, so there is no
ground truth to score their label against. We *do* know our own list exactly.
So: classify our own deck from all sixty cards, then classify it again from
only the cards we happened to reveal in each match, and compare. The second is
the same partial-information problem the opponent's label faces, against an
answer we can check.

    uv run python scripts/verify_archetypes.py [--db data/sensei-top.db]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from sensei_top.archetypes.classify import (
    card_colors_by_name,
    choose,
    load_definitions,
    rank_archetypes,
    seen_forms,
)
from sensei_top.db import connect
from sensei_top.formats import arena_format


def _card_names(conn: sqlite3.Connection, grp_ids: list[int]) -> list[str]:
    if not grp_ids:
        return []
    placeholders = ",".join("?" for _ in grp_ids)
    return [
        row["name"]
        for row in conn.execute(
            f"SELECT name FROM cards WHERE grp_id IN ({placeholders})", grp_ids
        )
    ]


def _revealed_by_seat(conn: sqlite3.Connection, column: str) -> dict[str, list[str]]:
    """Cards each match revealed for one seat, keyed by match.

    Grouped in Python rather than with GROUP_CONCAT: card names contain commas
    ("Momo, Friendly Flier"), so joining and re-splitting them would shatter
    exactly the names archetypes are identified by.
    """
    names: dict[str, list[str]] = {}
    for row in conn.execute(
        f"""
        SELECT m.match_id, c.name
          FROM matches m
          JOIN card_events ce ON ce.match_id = m.match_id AND ce.seat = m.{column}
          JOIN cards c ON c.grp_id = ce.grp_id
         WHERE instr(substr(c.type_line, 1,
                            instr(c.type_line || char(8212), char(8212))), 'Token') = 0
         GROUP BY m.match_id, c.name
        """
    ):
        names.setdefault(row["match_id"], []).append(row["name"])
    return names


def _colors_of(conn: sqlite3.Connection, names: list[str]) -> str:
    """Colour identity of a known card list, in WUBRG order."""
    letters = set()
    for name in names:
        row = conn.execute(
            "SELECT colors, type_line FROM cards WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        if row and row["colors"] and "Land" not in (row["type_line"] or ""):
            letters.update(json.loads(row["colors"]))
    return "".join(letter for letter in "WUBRG" if letter in letters)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="data/sensei-top.db")
    args = parser.parse_args()

    conn = connect(Path(args.db))
    conn.row_factory = sqlite3.Row
    definitions = load_definitions(conn)
    if not definitions:
        raise SystemExit("No archetype definitions stored. Run 'sensei-top archetypes' first.")

    colors_by_name = card_colors_by_name(conn)
    total = sum(len(v["archetype"]) + len(v["fallback"]) for v in definitions.values())
    print(f"Definitions: {total} across {', '.join(sorted(definitions))}\n")

    # --- 1. coverage --------------------------------------------------------
    rows = list(conn.execute("SELECT * FROM v_match_opponent"))
    by_source = Counter(r["opponent_source"] for r in rows)
    by_confidence = Counter(r["opponent_confidence"] for r in rows)
    print(f"Coverage over {len(rows)} matches")
    print(f"  by source     : {dict(by_source)}")
    print(f"  by confidence : {dict(by_confidence)}")
    named = sum(v for k, v in by_source.items() if k in ("archetype", "fallback", "manual"))
    print(f"  named         : {named}/{len(rows)} ({100 * named / max(len(rows), 1):.0f}%)\n")

    # --- 2. self-agreement, the ground-truth check --------------------------
    print("Self-agreement: our own deck, full list vs only what we revealed")
    agreements: list[tuple[int, bool]] = []
    for deck in conn.execute("SELECT deck_id, name, format, cards_json FROM decks"):
        fmt = arena_format(deck["format"], None)
        if fmt is None or fmt not in definitions:
            print(f"  {deck['name']}: format {deck['format']!r} not classifiable, skipped")
            continue

        maindeck = (json.loads(deck["cards_json"]) or {}).get("maindeck") or []
        full_names = _card_names(conn, maindeck)
        truth = choose(
            definitions[fmt]["archetype"], definitions[fmt]["fallback"],
            seen_forms(full_names), _colors_of(conn, full_names), colors_by_name,
            len(full_names), complete=True,
        )
        truth_label = truth.name if truth else "(unclassified)"
        print(f"  {deck['name']} — full {len(maindeck)} cards -> {truth_label}")

        our_cards = _revealed_by_seat(conn, "self_seat")
        for match in conn.execute(
            "SELECT match_id FROM matches WHERE deck_id = ? ORDER BY started_at",
            (deck["deck_id"],),
        ):
            revealed = our_cards.get(match["match_id"], [])
            if not revealed:
                continue
            partial = choose(
                definitions[fmt]["archetype"], definitions[fmt]["fallback"],
                seen_forms(revealed), _colors_of(conn, revealed), colors_by_name,
                len(revealed),
            )
            label = partial.name if partial else "(unclassified)"
            same = label == truth_label
            agreements.append((len(revealed), same))
            mark = "ok " if same else "DIFF"
            print(f"    {mark} {match['match_id'][:8]}  {len(revealed):>3} cards -> {label}")

    if agreements:
        hits = sum(1 for _, same in agreements if same)
        print(f"\n  agreement: {hits}/{len(agreements)} "
              f"({100 * hits / len(agreements):.0f}%)")
        buckets: dict[str, list[bool]] = {}
        for count, same in agreements:
            key = ("1-5" if count <= 5 else "6-10" if count <= 10
                   else "11-20" if count <= 20 else "21+")
            buckets.setdefault(key, []).append(same)
        print("  by cards revealed:")
        for key in ("1-5", "6-10", "11-20", "21+"):
            if seen := buckets.get(key):
                print(f"    {key:>6}: {sum(seen)}/{len(seen)}")

    # --- 3. how often the tie-break, not the evidence, decided --------------
    print("\nAmbiguity: how often the runner-up tied the winner")
    ties = 0
    considered = 0
    their_cards = _revealed_by_seat(conn, "opponent_seat")
    for match in conn.execute(
        """
        SELECT m.match_id, m.event_id, d.format AS deck_format
          FROM matches m LEFT JOIN decks d ON d.deck_id = m.deck_id
        """
    ):
        fmt = arena_format(match["deck_format"], match["event_id"])
        if fmt is None or fmt not in definitions:
            continue
        revealed = their_cards.get(match["match_id"], [])
        ranked = rank_archetypes(
            definitions[fmt]["archetype"], seen_forms(revealed), colors_by_name,
            _colors_of(conn, revealed), len(revealed),
        )
        if len(ranked) < 2:
            continue
        considered += 1
        if (ranked[0][1], ranked[0][2]) == (ranked[1][1], ranked[1][2]):
            ties += 1
            print(f"  {match['match_id'][:8]}: {ranked[0][0].key} tied {ranked[1][0].key}")
    print(f"  {ties}/{considered} decided by the file-stem tie-break")

    # --- 4. per-match detail, so a wrong label can be diagnosed -------------
    print("\nPer-match detail")
    for row in conn.execute(
        """
        SELECT m.opponent_name, m.result, o.opponent_label, o.opponent_source,
               o.opponent_confidence, o.opponent_cards_seen, a.evidence_json
          FROM v_match_opponent o
          JOIN matches m USING (match_id)
          LEFT JOIN opponent_archetype a USING (match_id)
         ORDER BY m.started_at
        """
    ):
        evidence = ", ".join(json.loads(row["evidence_json"] or "[]")) or "—"
        print(f"  {row['opponent_label'][:34]:<34} {row['opponent_confidence']:<8}"
              f" {row['opponent_cards_seen']:>3} cards   {evidence[:60]}")

    conn.close()


if __name__ == "__main__":
    main()
