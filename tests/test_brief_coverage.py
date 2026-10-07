"""Tests for brief/coverage.py's build_coverage: which archetypes are worth
a brief, and how well the ones this deck already has actually cover them.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.brief.coverage import build_coverage
from sensei_top.brief.store import Brief, list_hash, write_brief
from sensei_top.db import open_database
from sensei_top.guide.deck import DeckIdentity


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _card(conn, grp_id, name):
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) "
        "VALUES (?, ?, '{1}', 'Creature', 'Text.')",
        (grp_id, name),
    )


def _corpus_decks(conn, prefix, n, archetype_key, archetype_name, card_name="Filler Card",
                  fmt="Standard"):
    for i in range(n):
        event_id = f"{prefix}{i}"
        conn.execute(
            "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
            "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', '2026-08-15', "
            "?, 'B')",
            (event_id, fmt),
        )
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
            "losses) VALUES (?, 0, ?, '[]', 5, 0)",
            (event_id, json.dumps([{"count": 4, "name": card_name}])),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, 0, ?, ?, ?, "
            "'archetype', 'now')",
            (event_id, archetype_key, archetype_name, archetype_name),
        )


def _identity(deck_ids=("d1",), current_cards=None, fmt="Standard") -> DeckIdentity:
    return DeckIdentity(
        key="guid:x", arena_deck_id="x", name="My Deck", format=fmt,
        deck_ids=deck_ids, matches=0, match_wins=0, match_losses=0, games_won=0,
        games_lost=0, first_played="t", last_played="t",
        current_cards=current_cards or {"maindeck": [30, 30, 30, 30], "sideboard": []},
    )


def _seed_deck_and_matches(conn, deck_id, opponent_archetype_key, opponent_archetype_name, n):
    conn.execute(
        "INSERT OR IGNORE INTO decks (deck_id, name, format, cards_json, first_seen, "
        "last_seen) VALUES (?, 'My Deck', 'Standard', '{}', 't', 't')",
        (deck_id,),
    )
    for i in range(n):
        match_id = f"{deck_id}-{opponent_archetype_key}-{i}"
        result = "win" if i % 2 == 0 else "loss"
        conn.execute(
            "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
            "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
            "games_lost, completed_reason, format) VALUES (?, 'e', ?, 1, 2, 'u', 'n', 't', "
            "'t', ?, 2, 0, 'concede', 'Standard')",
            (match_id, deck_id, result),
        )
        conn.execute(
            "INSERT INTO opponent_archetype (match_id, format, archetype_key, "
            "archetype_name, colors, label, method, confidence, cards_seen, "
            "conditions_met, conditions_unknown, evidence_json, classified_at) VALUES "
            "(?, 'Standard', ?, ?, 'BR', ?, 'archetype', 'high', 3, '[]', '[]', '{}', 'now')",
            (match_id, opponent_archetype_key, opponent_archetype_name, opponent_archetype_name),
        )


def _write_brief(conn, identity, archetype_key, archetype_label, *, list_hash_value):
    brief = Brief(
        deck_key=identity.key, archetype_key=archetype_key, archetype_label=archetype_label,
        archetype_share=None, personal_matches=None, personal_wins=None, personal_losses=None,
        prose="p", play_around=(), board_in=(), board_out=(), staples=(), problems=(),
        prompt="prompt text", model="hand-written", generated_at="t", corpus_commit=None,
        list_hash=list_hash_value, source="live",
    )
    write_brief(conn, brief)


def test_build_coverage_unions_faced_and_top_field_archetypes_with_correct_status(conn):
    """7 corpus archetypes (field_1..field_7, deck counts 10..4) push
    field_7 out of the top TOP_FIELD_ARCHETYPES=6; two archetypes this deck
    has actually faced (field_3, in the top 6, and field_8, never in the
    corpus at all) complete the union. field_3 gets a fresh brief (ok),
    field_8 gets a brief stamped with a stale list_hash (stale); everything
    else stays missing — each has >= 5 windowed decklists, enough for a
    consensus to write from."""
    _card(conn, 30, "Opt")
    counts = {"field_1": 10, "field_2": 9, "field_3": 8, "field_4": 7,
              "field_5": 6, "field_6": 5, "field_7": 4}
    for key, n in counts.items():
        _corpus_decks(conn, key, n, key, key.replace("_", " ").title())

    _seed_deck_and_matches(conn, "d1", "field_3", "Field 3", 5)  # 3 wins, 2 losses
    _seed_deck_and_matches(conn, "d1", "field_8", "Field 8", 2)  # 1 win, 1 loss
    conn.commit()

    identity = _identity()
    current_hash = list_hash(identity.current_cards)
    _write_brief(conn, identity, "field_3", "Field 3", list_hash_value=current_hash)
    _write_brief(conn, identity, "field_8", "Field 8", list_hash_value="stale-hash-does-not-match")
    conn.commit()

    coverage = build_coverage(conn, identity)

    by_key = {row.archetype_key: row for row in coverage.rows}
    assert set(by_key) == {"field_1", "field_2", "field_3", "field_4", "field_5", "field_6",
                            "field_8"}
    assert "field_7" not in by_key  # 7th by deck count, and never faced: pushed out of the union

    assert by_key["field_3"].status == "ok"
    assert by_key["field_3"].times_faced == 5
    assert by_key["field_3"].field_share == pytest.approx(8 / 49)

    assert by_key["field_8"].status == "stale"
    assert by_key["field_8"].times_faced == 2
    # Never in the corpus, but the window itself isn't empty: a real 0, not unknown.
    assert by_key["field_8"].field_share == 0.0

    for key in ("field_1", "field_2", "field_4", "field_5", "field_6"):
        assert by_key[key].status == "missing"
        assert by_key[key].times_faced == 0
    assert by_key["field_1"].field_share == pytest.approx(10 / 49)
    assert by_key["field_6"].field_share == pytest.approx(5 / 49)

    # Row order: times_faced desc, then field_share desc, then key.
    assert [row.archetype_key for row in coverage.rows] == [
        "field_3", "field_8", "field_1", "field_2", "field_4", "field_5", "field_6",
    ]

    # Headlines: only field_3 (5 of the 7 classified, decided matches) is ok.
    assert coverage.matches_covered_numerator == 5
    assert coverage.matches_covered_denominator == 7
    assert coverage.matches_covered == pytest.approx(5 / 7)
    assert coverage.field_covered == pytest.approx(8 / 49)  # only field_3's own share


def test_build_coverage_matches_covered_is_none_with_no_classified_matches(conn):
    _card(conn, 30, "Opt")
    _corpus_decks(conn, "f", 6, "field_1", "Field 1")
    conn.commit()
    identity = _identity(deck_ids=())
    coverage = build_coverage(conn, identity)
    assert coverage.matches_covered is None
    assert coverage.matches_covered_numerator == 0
    assert coverage.matches_covered_denominator == 0
    assert coverage.field_covered == 0.0


def test_build_coverage_a_manual_only_opponent_label_is_not_a_row_or_a_denominator(conn):
    """A match whose opponent has no classifier archetype_key at all (a
    fallback/colours-only or manual-only verdict) is outside what this
    function can speak to — not a row, and not silently folded into either
    the numerator or the denominator (see build_coverage's own docstring)."""
    _card(conn, 30, "Opt")
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, format) VALUES ('m1', 'e', 'd1', 1, 2, 'u', 'n', 't', "
        "'t', 'win', 2, 0, 'concede', 'Standard')"
    )
    # No opponent_archetype row at all for m1 -> v_match_opponent.archetype_key is NULL.
    conn.commit()

    identity = _identity(deck_ids=("d1",))
    coverage = build_coverage(conn, identity)
    assert coverage.rows == ()
    assert coverage.matches_covered is None
    assert coverage.matches_covered_denominator == 0


def test_build_coverage_a_faced_archetype_too_thin_to_brief_is_no_consensus(conn):
    """field_7 has 4 windowed decklists — one short of build_consensus's
    5-deck floor — so with no brief it can't be closed from here: it is
    no_consensus, not missing, and still carries its real share (4/10)."""
    _card(conn, 30, "Opt")
    _corpus_decks(conn, "a", 6, "field_1", "Field 1")
    _corpus_decks(conn, "b", 4, "field_7", "Field 7")
    _seed_deck_and_matches(conn, "d1", "field_7", "Field 7", 1)
    conn.commit()

    coverage = build_coverage(conn, _identity())
    by_key = {row.archetype_key: row for row in coverage.rows}
    assert by_key["field_7"].status == "no_consensus"
    assert by_key["field_7"].times_faced == 1
    assert by_key["field_7"].field_share == pytest.approx(4 / 10)
    assert by_key["field_1"].status == "missing"
    assert by_key["field_1"].field_share == pytest.approx(6 / 10)


def test_build_coverage_two_keys_sharing_a_display_name_keep_their_own_shares(conn):
    """Two archetype keys the corpus labels with the same name (7 and 3
    decks) — the share is grouped by key, so neither inherits the other's."""
    _card(conn, 30, "Opt")
    _corpus_decks(conn, "a", 7, "key_a", "Shared Name")
    _corpus_decks(conn, "b", 3, "key_b", "Shared Name")
    conn.commit()

    coverage = build_coverage(conn, _identity(deck_ids=()))
    by_key = {row.archetype_key: row for row in coverage.rows}
    assert by_key["key_a"].field_share == pytest.approx(7 / 10)
    assert by_key["key_b"].field_share == pytest.approx(3 / 10)


def test_build_coverage_follows_the_decks_format(conn):
    """A Modern deck lists only Modern-corpus archetypes, even though the
    Standard corpus holds more decks of a different archetype."""
    _card(conn, 30, "Opt")
    _corpus_decks(conn, "s", 8, "std_arch", "Std Arch")
    _corpus_decks(conn, "m", 6, "mod_arch", "Mod Arch", fmt="Modern")
    conn.commit()
    coverage = build_coverage(conn, _identity(deck_ids=(), fmt="Modern"))
    assert coverage.fmt == "Modern"
    assert [r.archetype_key for r in coverage.rows] == ["mod_arch"]
    assert coverage.rows[0].field_share == 1.0
    # an explicit fmt still wins over the deck's own
    assert [
        r.archetype_key for r in build_coverage(conn, _identity(deck_ids=(), fmt="Modern"),
                                                fmt="Standard").rows
    ] == ["std_arch"]


def test_build_coverage_for_a_deck_with_no_format_is_empty(conn):
    _card(conn, 30, "Opt")
    _corpus_decks(conn, "s", 8, "std_arch", "Std Arch")
    conn.commit()
    coverage = build_coverage(conn, _identity(deck_ids=(), fmt=None))
    assert coverage.fmt is None
    assert coverage.rows == ()
    assert coverage.matches_covered is None
    assert coverage.field_covered == 0.0
