"""Tests for guide/bundle.py: assembling one deck's whole evidence bundle.
"""

from __future__ import annotations

import json

import pytest

import sensei_top.review.leaks as leaks_mod
from sensei_top.db import open_database
from sensei_top.guide.bundle import FORMAT_UNKNOWN_GAP, build_deck_guide


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_deck_and_match(conn, deck_id, match_id, maindeck, sideboard, result="win"):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'My Deck', 'Standard', ?, 't', 't')",
        (deck_id, json.dumps({"maindeck": maindeck, "sideboard": sideboard})),
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', "
        "'2026-08-15T00:00:00', 't', ?, 1, 0, 'r')",
        (match_id, deck_id, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 8, 0, 0)",
        (match_id, result),
    )


def test_unknown_key_returns_none(conn):
    conn.commit()
    assert build_deck_guide(conn, "deck:nonexistent") is None


def test_guide_assembles_with_no_matches_gap(conn):
    """A deck resolved by identity but with no matches must still produce a
    guide, with the gap stated rather than the whole thing failing."""
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide is not None
    assert guide.provenance.deck.key == "deck:d1"
    assert guide.list_diff is None  # no archetype definitions loaded
    assert any("classified" in g for g in guide.gaps)


def test_no_reset_gap_is_stated(conn):
    """With legality data present and nothing banned, "no reset" is a real
    answer about the corpus and may be stated as one."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text) "
        "VALUES (1, 'Some Card', 'Text.')"
    )
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (1, 'Standard', 'legal')"
    )
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide.provenance.reset is None
    assert any("No format reset" in g for g in guide.gaps)
    assert not any("legality" in g for g in guide.gaps)


def test_missing_legality_is_reported_as_a_hole_not_as_no_reset(conn):
    """Without legality data no ban is detectable, so the guide must not
    claim the corpus has no reset — it has no way to know, and every field
    number in it may pool across one."""
    conn.execute("INSERT INTO cards (grp_id, name, oracle_text) VALUES (1, 'Some Card', 'Text.')")
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide.provenance.reset is None
    assert not any("No format reset was detected" in g for g in guide.gaps)
    gap = next(g for g in guide.gaps if "legality" in g)
    assert "cards --scryfall" in gap


def test_oracle_coverage_gap_when_text_is_missing(conn):
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Some Card')")
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert guide.provenance.oracle_coverage == (0, 1)
    assert any("Rules text is missing" in g for g in guide.gaps)


def test_leaks_and_leaks_all_decks_are_both_present(conn):
    _insert_deck_and_match(conn, "d1", "m1", [1, 1, 1, 1], [])
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")
    assert isinstance(guide.leaks, tuple)
    assert isinstance(guide.leaks_all_decks, tuple)


# --- the deck's format (plan 13, D15) ---------------------------------------


def _store_corpus_deck(conn, event_id, deck_ord, fmt, event_date, mainboard, wins=0, losses=0):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, ?, 'B')",
        (event_id, event_date, fmt),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, wins, losses, mainboard_json, "
        "sideboard_json) VALUES (?, ?, ?, ?, ?, '[]')",
        (event_id, deck_ord, wins, losses,
         json.dumps([{"count": 4, "name": n} for n in mainboard])),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, 'arch', 'Arch', 'Arch', 'archetype', 'now')",
        (event_id, deck_ord),
    )


def _two_formats_with_one_ban_each(conn):
    """Card 10 is banned in Modern only and last played in Modern on
    2026-07-01; card 11 is banned in Standard only and last played in
    Standard on 2026-08-01. Two decks each, the floor a last appearance
    needs (``window.MIN_DECKS_FOR_LAST_APPEARANCE``). Modern's latest event
    is 2026-07-20, Standard's 2026-08-01."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (10, 'Modern Banned')")
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (11, 'Standard Banned')")
    conn.executemany(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (?, ?, ?)",
        [(10, "Modern", "banned"), (10, "Standard", "legal"),
         (11, "Standard", "banned"), (11, "Modern", "legal")],
    )
    for ord_ in (0, 1):
        _store_corpus_deck(conn, "mod1", ord_, "Modern", "2026-07-01", ["Modern Banned"])
        _store_corpus_deck(conn, "std1", ord_, "Standard", "2026-08-01", ["Standard Banned"])
    _store_corpus_deck(conn, "mod2", 0, "Modern", "2026-07-20", ["Other Card"])


def test_a_modern_decks_guide_reads_modern_resets_and_field(conn):
    """A ``.dek`` deck (no format on its record) picked for one Modern MTGO
    match is a Modern deck (D15's match step): its guide windows on Modern's
    ban, not Standard's, and its field is Modern's. The one match predates
    that ban, and it counts through the pick (``matches.deck_id`` is NULL)."""
    _two_formats_with_one_ban_each(conn)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('dek1', 'My Deck', NULL, ?, 't', 't')",
        (json.dumps({"maindeck": [10], "sideboard": []}),),
    )
    conn.execute(
        "INSERT INTO matches (match_id, started_at, ended_at, result, games_won, games_lost, "
        "source) VALUES ('mt1', '2026-06-15T00:00:00', 't', 'win', 2, 0, 'mtgo')"
    )
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES ('mt1', 'dek1', 'Modern')"
    )
    conn.commit()

    guide = build_deck_guide(conn, "deck:dek1")

    assert guide.provenance.reset is not None
    assert guide.provenance.reset.date == "2026-07-01"
    assert guide.provenance.reset.cards == ("Modern Banned",)
    assert guide.provenance.window_start == "2026-07-02"
    assert guide.provenance.matches_before_reset == 1
    assert guide.field.fmt == "Modern"
    assert guide.field.corpus_latest_event == "2026-07-20"
    assert FORMAT_UNKNOWN_GAP not in guide.gaps


def test_a_deck_with_no_format_gets_no_field_and_the_format_unknown_note(conn):
    """A Draft deck whose match the log names no format for: D15 gives NULL,
    so the guide carries no reset, no field and no list diff, and says why in
    the ``format_unknown`` note. Standard's corpus and ban are right there,
    and nothing of them is borrowed."""
    _two_formats_with_one_ban_each(conn)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'Draft Deck', 'Draft', ?, 't', 't')",
        (json.dumps({"maindeck": [11], "sideboard": []}),),
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES ('m1', 'e', 'd1', 1, 2, 'u', 'n', "
        "'2026-08-15T00:00:00', 't', 'win', 1, 0, 'r')"
    )
    conn.commit()

    guide = build_deck_guide(conn, "deck:d1")

    assert FORMAT_UNKNOWN_GAP in guide.gaps
    assert guide.provenance.reset is None
    assert guide.provenance.window_start is None
    assert guide.list_diff is None
    assert guide.field.fmt is None
    assert guide.field.shares == ()
    assert guide.field.classified_decks == 0
    assert guide.field.personal_rates == ()
    assert guide.field.own_performance is None
    # the field's own notes have nothing to speak about without a format
    assert not any("No format reset" in g or "legality" in g or "classified" in g
                   for g in guide.gaps)


def test_a_modern_deck_is_classified_under_modern_for_its_field_and_list_diff(conn):
    """Plan 13, S8: the guide classifies the user's own deck under the deck's
    format. The ``.dek`` record names none, so only the Modern pick makes it
    a Modern deck, and the Modern definition keyed ``arch`` is the one that
    names its card.

    By hand, from the seeded corpus: Modern's window starts 2026-07-02 (the
    ban on 2026-07-01). ``arch`` decks in it are mod2's one (0-0) and mod3's
    five (5-0, 4-1, 3-2, 3-1, 4-2): 6 decks, 19 wins, 6 losses, 19/25 = 0.76.
    mod1 (before the window) and std1 (Standard) are left out. The list diff's
    consensus is the five with at least 3 wins."""
    _two_formats_with_one_ban_each(conn)
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (12, 'Arch Card')")
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES ('Modern', 'archetype', 'arch', 'Arch', 0, ?, "
        "'2026-01-01T00:00:00Z')",
        (json.dumps({
            "Name": "Arch",
            "Conditions": [{"Type": "InMainboard", "Cards": ["Arch Card"]}],
        }),),
    )
    for ord_, (wins, losses) in enumerate([(5, 0), (4, 1), (3, 2), (3, 1), (4, 2)]):
        _store_corpus_deck(conn, "mod3", ord_, "Modern", "2026-07-25", ["Arch Card"],
                           wins=wins, losses=losses)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('dek1', 'My Deck', NULL, ?, 't', 't')",
        (json.dumps({"maindeck": [12, 12, 12, 12], "sideboard": []}),),
    )
    conn.execute(
        "INSERT INTO matches (match_id, started_at, ended_at, result, games_won, games_lost, "
        "source) VALUES ('mt1', '2026-06-15T00:00:00', 't', 'win', 2, 0, 'mtgo')"
    )
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES ('mt1', 'dek1', 'Modern')"
    )
    conn.commit()

    guide = build_deck_guide(conn, "deck:dek1")

    perf = guide.field.own_performance
    assert perf is not None
    assert (perf.decks, perf.wins, perf.losses, perf.win_rate) == (6, 19, 6, 0.76)
    assert guide.list_diff is not None
    assert guide.list_diff.archetype_key == "arch"
    assert guide.list_diff.winning_decks == 5


def test_a_leak_match_of_another_format_is_measured_against_that_formats_window(
    conn, monkeypatch,
):
    """The guide's leak rollups window each match by its own format, not
    by the deck's. By hand, from the seeded corpus: Standard's ban (last
    played 2026-08-01) opens its window on 2026-08-02, Modern's (2026-07-01)
    on 2026-07-02. The Standard deck holds one match of each format, so its
    Modern match takes Modern's window, in both rollups."""
    _two_formats_with_one_ban_each(conn)
    _insert_deck_and_match(conn, "d1", "m-standard", [11], [])
    conn.execute("UPDATE matches SET format = 'Standard' WHERE match_id = 'm-standard'")
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, format) VALUES ('m-modern', 'e', 'd1', 1, 2, 'u', "
        "'n', '2026-08-16T00:00:00', 't', 'loss', 0, 1, 'r', 'Modern')"
    )
    conn.commit()

    seen: list[tuple[str, str | None]] = []
    real_build_match_report = leaks_mod.build_match_report

    def recording_build_match_report(conn, match_id, *, consensus_since=None, **kwargs):
        seen.append((match_id, consensus_since))
        return real_build_match_report(
            conn, match_id, consensus_since=consensus_since, **kwargs
        )

    monkeypatch.setattr(leaks_mod, "build_match_report", recording_build_match_report)

    guide = build_deck_guide(conn, "deck:d1")

    assert guide.provenance.window_start == "2026-08-02"  # the deck's own: Standard
    # The deck-scoped rollup builds both reports; the all-decks one reuses them
    # from the shared report cache, keyed on the same windows.
    assert sorted(seen) == [("m-modern", "2026-07-02"), ("m-standard", "2026-08-02")]
