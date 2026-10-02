"""Tests for guide/narrative.py: the context and prompt ``full_prompt``
builds, and ``guide_narrative_from_json`` — the parser both the CLI import
and the API's generate route (``llm.write_json`` against this module's own
``_GUIDE_TOOL`` schema) converge on. The module itself no longer makes the
call (that moved to ``sensei_top.llm`` — see ``tests/test_llm.py``), so
there is nothing here to fake an SDK response for.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.db import open_database
from sensei_top.guide.bundle import (
    DeckGuide,
    PlayEvidence,
    Provenance,
)
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.field import FieldEvidence, archetype_key_by_name
from sensei_top.guide.list_diff import CardVerdict, ListDiff
from sensei_top.guide.narrative import (
    NarrativeError,
    build_guide_context,
    guide_narrative_from_json,
)


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _identity(matches=1, maindeck=None) -> DeckIdentity:
    return DeckIdentity(
        key="deck:d1", arena_deck_id=None, name="My Deck", format="Standard",
        deck_ids=("d1",), matches=matches, match_wins=1, match_losses=0, games_won=1,
        games_lost=0, first_played="t", last_played="t",
        current_cards={"maindeck": maindeck or [], "sideboard": []},
    )


def _empty_field() -> FieldEvidence:
    return FieldEvidence(
        fmt="Standard", window_start=None, classified_decks=0, shares=(), changes={},
        personal_rates=(), own_performance=None, corpus_fetched_at=None,
        corpus_latest_event=None,
    )


def _guide(*, matches=1, list_diff=None, maindeck=None) -> DeckGuide:
    identity = _identity(matches=matches, maindeck=maindeck)
    return DeckGuide(
        provenance=Provenance(
            deck=identity, reset=None, window_start=None, matches_before_reset=0,
            corpus_fetched_at=None, corpus_latest_event=None, classified_decks=0,
            oracle_coverage=(0, 0),
        ),
        play=PlayEvidence(board_curve={}, zone_curve={}, key_card_timing={},
                           mulligan_record={}, game_length={}),
        leaks=(), leaks_all_decks=(), list_diff=list_diff, field=_empty_field(), gaps=(),
    )


def test_build_guide_context_is_none_for_a_deck_with_no_matches(conn):
    guide = _guide(matches=0)
    assert build_guide_context(guide, conn=conn) is None


def test_build_guide_context_includes_deck_name_and_evidence(conn):
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) VALUES "
        "(1, 'Signature Card', 'Draw a card.', 'Sorcery', '{U}')"
    )
    guide = _guide(matches=5, maindeck=[1, 1, 1, 1])
    conn.commit()

    context = build_guide_context(guide, conn=conn)
    assert context is not None
    assert "My Deck" in context
    assert "Signature Card" in context
    assert "Draw a card." in context


def test_build_guide_context_lists_top_archetype_staples(conn):
    """Consensus staples and oracle text for the field's top archetypes
    (excluding the player's own) must appear in what gets sent."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) VALUES "
        "(1, 'Their Staple', 'Destroy target creature.', 'Instant', '{B}')"
    )
    for i in range(5):
        conn.execute(
            "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
            "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', '2026-08-15', "
            "'Standard', 'B')",
            (f"e{i}",),
        )
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins) "
            "VALUES (?, 0, ?, '[]', 3)",
            (f"e{i}", json.dumps([{"count": 4, "name": "Their Staple"}])),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES "
            "(?, 0, 'opp_arch', 'Opposing Archetype', 'Opposing Archetype', 'archetype', 'now')",
            (f"e{i}",),
        )
    guide = _guide(matches=1)
    field = FieldEvidence(
        fmt="Standard", window_start=None, classified_decks=5,
        shares=(_share("Opposing Archetype", 1.0),), changes={}, personal_rates=(),
        own_performance=None, corpus_fetched_at=None, corpus_latest_event=None,
    )
    guide = DeckGuide(
        provenance=guide.provenance, play=guide.play, leaks=(), leaks_all_decks=(),
        list_diff=None, field=field, gaps=(),
    )
    conn.commit()

    context = build_guide_context(guide, conn=conn)
    assert "Opposing Archetype" in context
    assert "Their Staple" in context
    assert "Destroy target creature." in context


def _share(archetype, share):
    from sensei_top.guide.field import ArchetypeShare
    return ArchetypeShare(archetype=archetype, decks=1, share=share,
                           share_before_reset=None, movement=None)


def test_build_guide_context_carries_no_local_paths(conn):
    """Same guard test_narrative.py carries for the match report — a
    filesystem path would reveal the machine, and this text can really
    leave it now that a credential can be configured."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) VALUES "
        "(1, 'Signature Card', 'Draw a card.', 'Sorcery', '{U}')"
    )
    guide = _guide(matches=5, maindeck=[1, 1, 1, 1])
    conn.commit()

    context = build_guide_context(guide, conn=conn)
    lowered = context.lower()
    for leaked in ("/home/", "c:\\users", "/users/", "appdata"):
        assert leaked not in lowered


_VALID_NARRATIVE = {
    "engine": "The deck discounts spells via graveyard count.",
    "fix": "Deploy earlier.",
    "card_notes": [{"card": "Opt", "verdict": "correct", "why": "cheap cantrip"}],
    "matchups": [{
        "archetype": "Mono-Green Landfall",
        "prose": "Board in sweepers.",
        "board_in": [{"card": "Slagstorm", "n": 2}],
        "board_out": [{"card": "Burst Lightning", "n": 2}],
    }],
    "checklist": ["Am I casting cantrips on curve?"],
}


def test_guide_narrative_from_json_parses_a_written_answer():
    guide = _guide(matches=1)
    result = guide_narrative_from_json(json.dumps(_VALID_NARRATIVE), guide)
    assert result.engine == "The deck discounts spells via graveyard count."
    assert result.fix == "Deploy earlier."
    assert result.card_notes[0].card == "Opt"
    assert result.matchups[0].archetype == "Mono-Green Landfall"
    assert result.matchups[0].board_in[0].card == "Slagstorm"
    assert result.checklist == ("Am I casting cantrips on curve?",)


def test_guide_narrative_from_json_accepts_an_already_parsed_dict():
    result = guide_narrative_from_json(_VALID_NARRATIVE, _guide(matches=1))
    assert result.fix == "Deploy earlier."


def test_import_validates_plans_against_the_real_75():
    """board_out names a card not in the recommended maindeck at all --
    plans.validate_plans must catch it and attach the problem rather than
    letting a wrong plan through or silently repairing it."""
    diff = ListDiff(
        archetype_key="k", archetype_name="Izzet Spellementals", winning_decks=10,
        min_wins=3,
        maindeck=(CardVerdict("Opt", 4, "main", 4.0, 1.0, 4, "correct"),),
        sideboard=(CardVerdict("Slagstorm", 2, "side", 2.0, 0.5, 2, "correct"),),
        duplicate_warnings=(),
    )
    guide = _guide(matches=1, list_diff=diff)

    result = guide_narrative_from_json(_VALID_NARRATIVE, guide)
    assert len(result.problems) >= 1
    assert any("Burst Lightning" in p.message for p in result.problems)


def test_guide_narrative_from_json_rejects_invalid_json():
    with pytest.raises(NarrativeError, match="not valid JSON"):
        guide_narrative_from_json("{not json at all", _guide())


def test_guide_narrative_from_json_rejects_a_non_object():
    with pytest.raises(NarrativeError, match="single JSON object"):
        guide_narrative_from_json("[1, 2, 3]", _guide())


def test_guide_narrative_from_json_rejects_missing_fields():
    with pytest.raises(NarrativeError, match="missing or malformed"):
        guide_narrative_from_json(json.dumps({"engine": "ok"}), _guide())


# --- S7: the archetypes this deck actually faces, alongside the field's top ---

_WINDOW = "2026-08-11"


def _card_row(conn, grp_id, name, oracle):
    conn.execute(
        "INSERT INTO cards (grp_id, name, oracle_text, type_line, mana_cost) VALUES "
        "(?, ?, ?, 'Instant', '{B}')",
        (grp_id, name, oracle),
    )


def _corpus(conn, prefix, n, key, name, card):
    """n classified decks for (key, name), each playing 4x card, dated
    inside _WINDOW — enough for build_consensus once n >= 5."""
    for i in range(n):
        event_id = f"{prefix}{i}"
        conn.execute(
            "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
            "format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', '2026-08-15', 'Standard', 'B')",
            (event_id,),
        )
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins) "
            "VALUES (?, 0, ?, '[]', 3)",
            (event_id, json.dumps([{"count": 4, "name": card}])),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES (?, 0, ?, ?, ?, "
            "'archetype', 'now')",
            (event_id, key, name, name),
        )


def _faced(conn, key, name, n, *, started_at="2026-08-20T12:00:00"):
    """n decided matches of deck d1 against a classifier verdict (key, name)."""
    conn.execute(
        "INSERT OR IGNORE INTO decks (deck_id, name, format, cards_json, first_seen, "
        "last_seen) VALUES ('d1', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    for i in range(n):
        match_id = f"{key}-{started_at}-{i}"
        conn.execute(
            "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
            "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
            "games_lost, completed_reason) VALUES (?, 'e', 'd1', 1, 2, 'u', 'n', ?, ?, "
            "'loss', 0, 2, 'concede')",
            (match_id, started_at, started_at),
        )
        conn.execute(
            "INSERT INTO opponent_archetype (match_id, format, archetype_key, "
            "archetype_name, colors, label, method, confidence, cards_seen, "
            "conditions_met, conditions_unknown, evidence_json, classified_at) VALUES "
            "(?, 'Standard', ?, ?, 'B', ?, 'archetype', 'high', 3, '[]', '[]', '{}', 'now')",
            (match_id, key, name, name),
        )


def _windowed_guide(shares=()) -> DeckGuide:
    base = _guide(matches=5)
    provenance = Provenance(
        deck=base.provenance.deck, reset=None, window_start=_WINDOW, matches_before_reset=0,
        corpus_fetched_at=None, corpus_latest_event=None, classified_decks=0,
        oracle_coverage=(0, 0),
    )
    field = FieldEvidence(
        fmt="Standard", window_start=_WINDOW, classified_decks=0, shares=shares, changes={},
        personal_rates=(), own_performance=None, corpus_fetched_at=None,
        corpus_latest_event=None,
    )
    return DeckGuide(
        provenance=provenance, play=base.play, leaks=(), leaks_all_decks=(), list_diff=None,
        field=field, gaps=(),
    )


def test_build_guide_context_adds_archetypes_faced_at_least_three_times_in_the_window(conn):
    """Top Arch is the field's only listed share. Faced Arch was faced 3
    times since the window opened (in); Rare Arch twice (under the floor);
    Old Arch 3 times, all before the window (out). Each has 5 corpus decks,
    so only the faced-count rules decide."""
    for grp_id, (key, name) in enumerate(
        [("top", "Top Arch"), ("faced", "Faced Arch"), ("rare", "Rare Arch"),
         ("old", "Old Arch")], start=1,
    ):
        _card_row(conn, grp_id, f"{name} Staple", f"{name} oracle text.")
        _corpus(conn, key, 5, key, name, f"{name} Staple")
    _faced(conn, "faced", "Faced Arch", 3)
    _faced(conn, "rare", "Rare Arch", 2)
    _faced(conn, "old", "Old Arch", 3, started_at="2026-08-01T12:00:00")
    conn.commit()

    context = build_guide_context(_windowed_guide((_share("Top Arch", 0.5),)), conn=conn)

    assert "-- Top Arch (50.0% of the field) --" in context
    assert (
        "-- Faced Arch (you faced it 3 times since the reset; "
        "not among the field's top archetypes) --"
    ) in context
    assert "Faced Arch oracle text." in context
    assert "Rare Arch" not in context
    assert "Old Arch" not in context


def test_build_guide_context_caps_faced_archetypes_at_five_most_faced(conn):
    """Six archetypes faced 8, 7, 6, 5, 4 and 3 times: only the five most
    faced are listed, in that order; the one faced 3 times is dropped."""
    faced_counts = {"f1": 8, "f2": 7, "f3": 6, "f4": 5, "f5": 4, "f6": 3}
    for grp_id, (key, n) in enumerate(faced_counts.items(), start=1):
        _card_row(conn, grp_id, f"Staple {key}", f"Text {key}.")
        _corpus(conn, key, 5, key, f"Arch {key}", f"Staple {key}")
        _faced(conn, key, f"Arch {key}", n)
    conn.commit()

    context = build_guide_context(_windowed_guide(), conn=conn)

    positions = [context.index(f"-- Arch {key} (") for key in ("f1", "f2", "f3", "f4", "f5")]
    assert positions == sorted(positions)
    assert "Arch f6" not in context


def test_build_guide_context_resolves_a_shared_name_to_its_majority_key(conn):
    """"Shared Midrange" labels 6 decks under key 'majority' and 1 under
    'minority' — inserted last, so a last-row-wins lookup would pick
    'minority', find no consensus behind 1 deck, and drop the archetype."""
    _card_row(conn, 1, "Majority Staple", "Majority oracle text.")
    _card_row(conn, 2, "Minority Staple", "Minority oracle text.")
    _corpus(conn, "a", 6, "majority", "Shared Midrange", "Majority Staple")
    _corpus(conn, "b", 1, "minority", "Shared Midrange", "Minority Staple")
    conn.commit()

    assert archetype_key_by_name(conn) == {"Shared Midrange": "majority"}
    context = build_guide_context(
        _windowed_guide((_share("Shared Midrange", 0.9),)), conn=conn,
    )
    assert "-- Shared Midrange (90.0% of the field) --" in context
    assert "Majority oracle text." in context


def test_build_guide_context_gives_a_shared_staples_oracle_text_once(conn):
    """Two archetypes both register Shared Staple; its oracle text is
    printed under the first and only named under the second."""
    _card_row(conn, 1, "Shared Staple", "A distinctive oracle sentence.")
    _corpus(conn, "a", 5, "one", "Arch One", "Shared Staple")
    _corpus(conn, "b", 5, "two", "Arch Two", "Shared Staple")
    conn.commit()

    context = build_guide_context(
        _windowed_guide((_share("Arch One", 0.5), _share("Arch Two", 0.5))), conn=conn,
    )
    assert context.count("A distinctive oracle sentence.") == 1
    assert context.count("4.0x Shared Staple") == 2
