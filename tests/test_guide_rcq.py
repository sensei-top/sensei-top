"""Tests for guide/rcq.py: the RCQ guide's evidence (``build_rcq``). Its prompt
and the answer's parser are tests/ai/test_guide_rcq_prompt.py.

Every corpus row is synthetic and inserted here, the way the deck guide's
own tests build theirs; each expectation is read off those rows (counts,
dates, placements), never off the code's output.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from sensei_top.db import open_database
from sensei_top.guide.rcq import (
    build_rcq,
)

TODAY = date(2026, 10, 3)
PASTED = """Deck
4 Own Card (ABC) 1
56 Mountain (ABC) 2

Sideboard
2 Side Card (ABC) 3
1 Front Face (ABC) 4
"""


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _card_row(conn, grp_id, name, oracle):
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) VALUES "
        "(?, ?, ?, 'Instant', '{R}')",
        (grp_id, name, oracle),
    )


def _event(conn, event_id, event_date, *, name="e", source="MTGO", duplicate_of=None):
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, format, "
        "tier, duplicate_of) VALUES (?, 'p', 's', ?, ?, ?, 'Standard', 'B', ?)",
        (event_id, source, name, event_date, duplicate_of),
    )


def _deck(conn, event_id, deck_ord, card, *, key=None, name=None, result=None):
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, result, mainboard_json, sideboard_json, "
        "wins) VALUES (?, ?, ?, ?, '[]', 3)",
        (event_id, deck_ord, result, json.dumps([{"count": 4, "name": card}])),
    )
    if key is not None:
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, ?, ?, ?, ?, "
            "'archetype', 'now')",
            (event_id, deck_ord, key, name, name),
        )


def _corpus(conn, key, n, *, event_date="2026-09-20"):
    """n classified decks of archetype key ("Arch <key>"), one event each,
    every deck playing 4x "Staple <key>" — a consensus once n >= 5."""
    for i in range(n):
        _event(conn, f"{key}-{i}", event_date)
        _deck(conn, f"{key}-{i}", 0, f"Staple {key}", key=key, name=f"Arch {key}")


def _own_deck(conn):
    """Deck d1 and one won match with it, so build_deck_guide resolves it."""
    _card_row(conn, 1, "Own Card", "Own card text.")
    _card_row(conn, 2, "Mountain", None)
    _card_row(conn, 3, "Side Card", "Side card text.")
    _card_row(conn, 4, "Front Face // Back Face", "Double-faced text.")
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', ?, 't', 't')",
        (json.dumps({"maindeck": [1] * 4 + [2] * 56, "sideboard": [3, 3]}),),
    )
    _match(conn, "m-own", "2026-09-28T12:00:00", "win")


def _match(conn, match_id, started_at, result):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, format) VALUES (?, 'e', 'd1', 1, 2, 'u', 'n', ?, ?, "
        "?, ?, ?, 'concede', 'Standard')",
        (match_id, started_at, started_at, result,
         2 if result == "win" else 0, 0 if result == "win" else 2),
    )


def test_recent_shares_cover_the_last_fourteen_days_only(conn):
    """09-19 is the window's first day (14 back from 10-03): a1's 3 decks
    there count, a2's 2 decks on 09-18 do not."""
    _own_deck(conn)
    _corpus(conn, "a1", 3, event_date="2026-09-19")
    _corpus(conn, "a2", 2, event_date="2026-09-18")
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)

    assert evidence.recent_classified_decks == 3
    assert [(s.archetype, s.decks, s.share) for s in evidence.recent_shares] == [
        ("Arch a1", 3, 1.0),
    ]


def _teach_own_archetype(conn):
    """One Standard definition, "Burn", that needs Own Card in the
    maindeck (the shape tests/test_metagame.py::_teach_meta stores), and
    five corpus Burn decks with 3 wins each — the consensus floor
    build_list_diff reads (min_decks=5, min_wins=3). The corpus lists
    play Own Card and Mountain, never Side Card."""
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES ('Standard', 'archetype', 'Burn', 'Burn', 0, ?, "
        "'2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Burn",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Own Card"]}]}),),
    )
    for i in range(5):
        _event(conn, f"burn-{i}", "2026-09-20")
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins) "
            "VALUES (?, 0, ?, '[]', 3)",
            (f"burn-{i}", json.dumps([{"count": 4, "name": "Own Card"},
                                      {"count": 56, "name": "Mountain"}])),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, 0, 'Burn', 'Burn', "
            "'Burn', 'archetype', 'now')",
            (f"burn-{i}",),
        )


def test_the_pasted_75_is_classified_and_diffed_against_its_consensus(conn):
    _own_deck(conn)
    _teach_own_archetype(conn)
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, [], today=TODAY)

    assert evidence.own_verdict_key == "Burn"
    assert evidence.own_unclassified_reason is None
    # Front Face is only in the pasted sideboard (d1's own list has none)
    assert "Front Face // Back Face" in {c.card for c in evidence.list_diff.sideboard}


def test_an_own_pick_the_corpus_does_not_know_gives_a_reason_and_no_diff(conn):
    _own_deck(conn)
    _teach_own_archetype(conn)
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, [], own="missing", today=TODAY)

    assert evidence.own_verdict_key is None
    assert evidence.own_unclassified_reason is not None
    assert evidence.list_diff is None


def test_a_deck_with_no_format_builds_without_a_field(conn):
    """No deck format and no played match with a resolvable format: the
    guide has no field, so the RCQ build has no shares, events or diff, and
    the pasted 75 is not classified against a borrowed format."""
    _own_deck(conn)
    _teach_own_archetype(conn)
    conn.execute("UPDATE decks SET format = NULL")
    conn.execute("UPDATE matches SET format = NULL")
    conn.commit()

    evidence = build_rcq(conn, "deck:d1", PASTED, ["a1"], today=TODAY)

    assert evidence.guide.field.fmt is None
    assert evidence.own_verdict_key is None
    assert evidence.own_unclassified_reason is not None
    assert evidence.list_diff is None
    assert evidence.recent_shares == ()
    assert evidence.recent_classified_decks == 0
    assert evidence.recent_events == ()
    assert evidence.expected == ()
    assert evidence.unknown_expected == ("a1",)
    assert evidence.own_unclassified_reason == (
        "The deck's format is unknown, so this 75 was not classified: "
        "archetype definitions are kept per format."
    )


def test_unknown_deck_key_is_none(conn):
    conn.commit()
    assert build_rcq(conn, "deck:nope", PASTED, [], today=TODAY) is None
