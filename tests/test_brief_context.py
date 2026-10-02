"""Tests for brief/narrative.py's build_brief_context: what gets sent, and
— the property the whole feature depends on — what never does.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.brief.narrative import (
    NarrativeError,
    briefs_from_json,
    build_brief_context,
    full_multi_prompt,
)
from sensei_top.db import open_database
from sensei_top.guide.deck import DeckIdentity


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _card(conn, grp_id, name, *, type_line="Creature", mana_cost="{1}{B}", oracle_text="Text."):
    conn.execute(
        "INSERT INTO cards (grp_id, name, mana_cost, type_line, oracle_text) "
        "VALUES (?, ?, ?, ?, ?)",
        (grp_id, name, mana_cost, type_line, oracle_text),
    )


def _store_deck(conn, event_id, deck_ord, archetype_key, archetype_name, mainboard, *,
                 event_date="2026-08-15", wins=5, losses=0):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, 'Standard', 'B')",
        (event_id, event_date),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
        "losses) VALUES (?, ?, ?, '[]', ?, ?)",
        (event_id, deck_ord, json.dumps(mainboard), wins, losses),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, ?, ?, 'archetype', 'now')",
        (event_id, deck_ord, archetype_key, archetype_name, archetype_name),
    )


def _identity(deck_ids=(), current_cards=None) -> DeckIdentity:
    return DeckIdentity(
        key="guid:x", arena_deck_id="x", name="My Deck", format="Standard",
        deck_ids=deck_ids, matches=0, match_wins=0, match_losses=0, games_won=0,
        games_lost=0, first_played=None, last_played=None,
        current_cards=current_cards or {"maindeck": [], "sideboard": []},
    )


def _seed_matchup(conn):
    _card(conn, 1, "Marauding Mako", oracle_text="Menace.")
    _card(
        conn, 2, "Erode", type_line="Instant", mana_cost="{B}",
        oracle_text="Destroy target creature.",
    )
    for i in range(6):
        _store_deck(
            conn, f"e{i}", 0, "mardu_discard", "Mardu Discard",
            [{"count": 4, "name": "Marauding Mako"}, {"count": 4, "name": "Erode"}],
        )


def test_context_names_opponent_staples_and_the_players_75(conn):
    _seed_matchup(conn)
    _card(
        conn, 10, "Slagstorm", type_line="Sorcery",
        oracle_text="Deal 3 damage to each creature.",
    )
    conn.commit()

    identity = _identity(current_cards={"maindeck": [10, 10, 10, 10], "sideboard": []})
    built = build_brief_context(conn, identity, "mardu_discard", "Mardu Discard")
    assert built is not None
    context, facts = built

    assert "Marauding Mako" in context
    assert "Erode" in context
    assert "Slagstorm" in context
    assert any(s.name == "Marauding Mako" for s in facts.staples)


def _ban(conn, name):
    conn.execute(
        "INSERT INTO cards (grp_id, name, standard_legality) VALUES (?, ?, 'banned')",
        (hash(name) % 1_000_000, name),
    )


def test_field_data_is_windowed_to_a_detected_reset(conn):
    """A brief must never pool consensus/share data across an undetected
    reset — the same failure guide/window.py exists to prevent
    (docs/metagame.md's "format-reset boundary"). Pre-reset Mardu Discard
    decks run a since-banned card and a staple that must not leak into the
    windowed consensus; post-reset decks alone must clear build_consensus's
    own min_decks (5) and be the whole share denominator."""
    _ban(conn, "Badgermole Cub")
    # MIN_DECKS_FOR_LAST_APPEARANCE (2) counts decks *on the same date* —
    # both on 2026-08-03, so that date is real evidence of the last day the
    # card was actually played, not a single stray appearance.
    for i in range(2):
        _store_deck(
            conn, f"ban{i}", 0, "other_arch", "Other Archetype",
            [{"count": 4, "name": "Badgermole Cub"}], event_date="2026-08-03",
        )
    for i in range(6):
        _store_deck(
            conn, f"pre{i}", 0, "mardu_discard", "Mardu Discard",
            [{"count": 4, "name": "Old Staple"}], event_date="2026-08-01",
        )
    for i in range(6):
        _store_deck(
            conn, f"post{i}", 0, "mardu_discard", "Mardu Discard",
            [{"count": 4, "name": "New Staple"}], event_date="2026-08-15",
        )
    _card(conn, 500, "Old Staple")
    _card(conn, 501, "New Staple")
    conn.commit()

    identity = _identity()
    built = build_brief_context(conn, identity, "mardu_discard", "Mardu Discard")
    assert built is not None
    context, facts = built

    assert "New Staple" in context
    assert "Old Staple" not in context
    assert any(s.name == "New Staple" for s in facts.staples)
    assert not any(s.name == "Old Staple" for s in facts.staples)
    assert facts.archetype_share == pytest.approx(1.0)  # only post-reset decks are Mardu Discard
    assert "format reset was detected" in context.lower()


def _store_round(conn, event_id, *, event_date, own_key, opp_key, own_wins, opp_wins, tier="A"):
    """One meta_round_match row between the user's own archetype (deck_ord
    0) and the briefed-against opponent archetype (deck_ord 1) — what
    `_opponent_section`'s "Field record for this pairing" line reads from
    `v_meta_matchup` via `ranked_field_matchup`. `source` is derived from
    `tier` (MTGO for B/C, MTGmelee for A/D — the spellings `source.py`
    stores) so the row is one the classifier could actually have produced."""
    source = "MTGO" if tier in ("B", "C") else "MTGmelee"
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', ?, 'e', ?, 'Standard', ?)",
        (event_id, source, event_date, tier),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
        "VALUES (?, 0, '[]', '[]')",
        (event_id,),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
        "VALUES (?, 1, '[]', '[]')",
        (event_id,),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, 0, ?, ?, ?, 'archetype', 'now')",
        (event_id, own_key, own_key, own_key),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, 1, ?, ?, ?, 'archetype', 'now')",
        (event_id, opp_key, opp_key, opp_key),
    )
    conn.execute(
        "INSERT INTO meta_round_match (event_id, round_name, deck_ord_a, deck_ord_b, "
        "wins_a, wins_b, draws) VALUES (?, 'Round 1', 0, 1, ?, ?, 0)",
        (event_id, own_wins, opp_wins),
    )


def test_field_record_line_counts_only_post_window_rounds_and_says_since(conn):
    """The "Field record for this pairing" line must not pool a pre-reset
    round into a post-reset record — the same failure
    test_field_data_is_windowed_to_a_detected_reset pins for the consensus
    decklist, but for the field's own match record instead."""
    _ban(conn, "Old Ban Card")
    # MIN_DECKS_FOR_LAST_APPEARANCE (2) on the same date — real evidence of
    # the ban's last-played day, not a stray appearance.
    for i in range(2):
        _store_deck(
            conn, f"ban{i}", 0, "other_arch", "Other Archetype",
            [{"count": 4, "name": "Old Ban Card"}], event_date="2026-08-05",
        )
    # window_start is the day after the ban's last-seen date: 2026-08-06.
    _card(conn, 600, "Field Staple")
    for i in range(6):
        _store_deck(
            conn, f"cons{i}", 0, "mardu_discard", "Mardu Discard",
            [{"count": 4, "name": "Field Staple"}], event_date="2026-08-10",
        )
    # One pre-window round (own wins) and one post-window round (own loses).
    _store_round(
        conn, "preA", event_date="2026-08-01",
        own_key="izzet_control", opp_key="mardu_discard", own_wins=1, opp_wins=0,
    )
    _store_round(
        conn, "postA", event_date="2026-08-10",
        own_key="izzet_control", opp_key="mardu_discard", own_wins=0, opp_wins=1,
    )
    conn.commit()

    identity = _identity()
    built = build_brief_context(
        conn, identity, "mardu_discard", "Mardu Discard", own_archetype_key="izzet_control",
    )
    assert built is not None
    context, _facts = built

    assert "since 2026-08-06" in context
    assert (
        "Field record for this pairing, from paper tournaments of 64 or more players "
        "since 2026-08-06: 0-1 across 1 matches." in context
    )
    # The pre-window round's own-win must not leak into the shown total.
    assert "1-0 across 2 matches" not in context
    assert "0-1 across 2 matches" not in context


def test_unwindowed_context_says_whether_it_could_even_look_for_a_reset(conn):
    """Same un-windowed numbers, two different reasons, and the brief must
    not report them the same way: with legality data and nothing banned the
    corpus really has no reset; without it, no ban is detectable and the
    shares below may pool across one."""
    _seed_matchup(conn)  # cards inserted with no standard_legality
    conn.commit()
    identity = _identity()

    context, _ = build_brief_context(conn, identity, "mardu_discard", "Mardu Discard")
    assert "no format reset detected" not in context.lower()
    assert "no card legality data is present" in context.lower()

    conn.execute("UPDATE cards SET standard_legality = 'legal' WHERE grp_id = 1")
    conn.commit()
    context, _ = build_brief_context(conn, identity, "mardu_discard", "Mardu Discard")
    assert "no format reset detected" in context.lower()
    assert "legality" not in context.lower()


def test_returns_none_when_archetype_has_no_consensus(conn):
    conn.commit()
    identity = _identity()
    assert build_brief_context(conn, identity, "nonexistent_archetype", "Nonexistent") is None


def test_context_never_carries_any_game_in_progress_signal(conn):
    """The property the whole feature's cheapness and its reading of
    AGENTS.md rule 5 depend on: a brief is a function of two decklists and
    the field, never of a game. Seed a live match with distinctive life
    totals, turn numbers, and zone rows, and confirm none of those values
    leak into the context build_brief_context assembles.
    """
    _seed_matchup(conn)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES ('m1', 'e', 'd1', 1, 2, 'u', 'n', 't', NULL, "
        "'incomplete', 0, 0, NULL)"
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES ('m1', 1, 1, 'incomplete', NULL, "
        "13, 0, 0)"
    )
    distinctive_life = 9911
    distinctive_turn = 8877
    conn.execute(
        "INSERT INTO turns (match_id, game_number, turn_number, active_seat, self_life, "
        "opp_life, self_hand, opp_hand, self_lands, self_permanents, opp_permanents) "
        "VALUES ('m1', 1, ?, 1, ?, 4, 3, 3, 4, 2, 1)",
        (distinctive_turn, distinctive_life),
    )
    conn.commit()

    identity = _identity(
        deck_ids=("d1",), current_cards={"maindeck": [1, 1, 1, 1], "sideboard": []}
    )
    built = build_brief_context(conn, identity, "mardu_discard", "Mardu Discard")
    assert built is not None
    context, _facts = built

    assert str(distinctive_life) not in context
    assert str(distinctive_turn) not in context
    assert "match_id" not in context.lower()
    assert "m1" not in context
    # The prompt's own closing disclaimer names what is deliberately absent
    # (see build_brief_context's "not given to you" block) — its presence
    # as prose is fine; what matters is that no *value* from the seeded
    # match (life, turn, match id) ever appears above.
    assert "no game in progress" in context.lower() or "not a specific game" in context.lower()


# --- full_multi_prompt (already written; these pin its existing behaviour) --


def test_full_multi_prompt_names_own_75_once(conn):
    _seed_matchup(conn)  # mardu_discard, staples Marauding Mako + Erode
    for i in range(6):
        _store_deck(
            conn, f"g{i}", 0, "izzet_control", "Izzet Control",
            [{"count": 4, "name": "Second Staple"}],
        )
    _card(
        conn, 20, "Second Staple", type_line="Instant", mana_cost="{U}",
        oracle_text="Counter target spell.",
    )
    _card(conn, 30, "Opt")
    conn.commit()

    identity = _identity(current_cards={"maindeck": [30, 30, 30, 30], "sideboard": []})
    built = full_multi_prompt(
        conn, identity, [("mardu_discard", "Mardu Discard"), ("izzet_control", "Izzet Control")],
    )
    assert built is not None
    assert built.prompt.count("Your current 75:") == 1
    assert built.included == ("mardu_discard", "izzet_control")


def test_full_multi_prompt_prints_a_shared_staples_oracle_text_once(conn):
    """A card run by two archetypes' consensus decks must have its oracle
    text block printed once, not once per matchup — _opponent_section's own
    shown_grp_ids dedup, exercised here across two archetypes rather than
    within one."""
    _card(
        conn, 100, "Shared Staple", type_line="Creature", mana_cost="{2}{B}",
        oracle_text="UNIQUE ORACLE MARKER TEXT.",
    )
    for i in range(6):
        _store_deck(
            conn, f"a{i}", 0, "arch_a", "Archetype A",
            [{"count": 4, "name": "Shared Staple"}],
        )
    for i in range(6):
        _store_deck(
            conn, f"b{i}", 0, "arch_b", "Archetype B",
            [{"count": 4, "name": "Shared Staple"}],
        )
    conn.commit()

    identity = _identity()
    built = full_multi_prompt(
        conn, identity, [("arch_a", "Archetype A"), ("arch_b", "Archetype B")],
    )
    assert built is not None
    assert built.prompt.count("UNIQUE ORACLE MARKER TEXT.") == 1
    # The card is still named (with its own count/share) in both sections'
    # decklists — only the oracle text block itself is deduped.
    assert built.prompt.count("Shared Staple") >= 2


def test_full_multi_prompt_reports_no_consensus_and_deferred(conn):
    _seed_matchup(conn)  # mardu_discard has consensus
    for i in range(6):
        _store_deck(
            conn, f"c{i}", 0, "izzet_control", "Izzet Control",
            [{"count": 4, "name": "Erode"}],
        )
    conn.commit()

    identity = _identity()
    archetypes = [
        ("ghost_archetype", "Ghost Archetype"),  # never in the corpus: no consensus
        ("mardu_discard", "Mardu Discard"),
        ("izzet_control", "Izzet Control"),
        ("third_archetype", "Third Archetype"),  # would have consensus, but past the limit
    ]
    built = full_multi_prompt(conn, identity, archetypes, limit=2)
    assert built is not None
    assert built.included == ("mardu_discard", "izzet_control")
    assert built.no_consensus == ("ghost_archetype",)
    assert built.deferred == ("third_archetype",)


def test_full_multi_prompt_never_carries_any_game_in_progress_signal(conn):
    """Same property as build_brief_context's own version of this test
    (test_context_never_carries_any_game_in_progress_signal), pinned for the
    several-archetype prompt too — no board, no turn, no life, no match id,
    even with a live in-progress match seeded for this deck."""
    _seed_matchup(conn)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES ('m1', 'e', 'd1', 1, 2, 'u', 'n', 't', NULL, "
        "'incomplete', 0, 0, NULL)"
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES ('m1', 1, 1, 'incomplete', NULL, "
        "13, 0, 0)"
    )
    distinctive_life = 9911
    distinctive_turn = 8877
    conn.execute(
        "INSERT INTO turns (match_id, game_number, turn_number, active_seat, self_life, "
        "opp_life, self_hand, opp_hand, self_lands, self_permanents, opp_permanents) "
        "VALUES ('m1', 1, ?, 1, ?, 4, 3, 3, 4, 2, 1)",
        (distinctive_turn, distinctive_life),
    )
    conn.commit()

    identity = _identity(
        deck_ids=("d1",), current_cards={"maindeck": [1, 1, 1, 1], "sideboard": []}
    )
    built = full_multi_prompt(conn, identity, [("mardu_discard", "Mardu Discard")])
    assert built is not None

    assert str(distinctive_life) not in built.prompt
    assert str(distinctive_turn) not in built.prompt
    assert "match_id" not in built.prompt.lower()
    assert "m1" not in built.prompt
    assert (
        "no game in progress" in built.prompt.lower()
        or "not a specific game" in built.prompt.lower()
    )


# --- briefs_from_json --------------------------------------------------------


_ONE_VALID_BRIEF = {
    "archetype_key": "mardu_discard",
    "prose": "Race early.",
    "play_around": [],
    "board_in": [],
    "board_out": [],
}


def test_briefs_from_json_rejects_an_empty_array():
    with pytest.raises(NarrativeError, match="non-empty 'briefs' array"):
        briefs_from_json({"briefs": []})


def test_briefs_from_json_rejects_an_item_with_no_archetype_key():
    item = dict(_ONE_VALID_BRIEF)
    del item["archetype_key"]
    with pytest.raises(NarrativeError, match="has no archetype_key"):
        briefs_from_json({"briefs": [item]})


def test_briefs_from_json_rejects_a_duplicate_archetype_key():
    with pytest.raises(NarrativeError, match="appears twice"):
        briefs_from_json({"briefs": [_ONE_VALID_BRIEF, dict(_ONE_VALID_BRIEF)]})


def test_briefs_from_json_rejects_a_malformed_item():
    item = dict(_ONE_VALID_BRIEF)
    del item["prose"]
    with pytest.raises(NarrativeError, match="missing or malformed field"):
        briefs_from_json({"briefs": [item]})


def test_briefs_from_json_parses_every_valid_item():
    second = dict(_ONE_VALID_BRIEF, archetype_key="izzet_control", prose="Play around counters.")
    out = briefs_from_json({"briefs": [_ONE_VALID_BRIEF, second]})
    assert [key for key, _ in out] == ["mardu_discard", "izzet_control"]
    assert out[0][1]["prose"] == "Race early."
    assert out[1][1]["prose"] == "Play around counters."
