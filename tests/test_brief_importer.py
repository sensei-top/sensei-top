"""Tests for brief/importer.py and guide/authored.py: storing an authored
brief or guide narrative — the CLI import path both keep regardless of
whether a Claude credential is configured (AGENTS.md non-negotiable #5,
`docs/llm.md`).
"""

from __future__ import annotations

import json

import pytest

from sensei_top.brief import store
from sensei_top.brief.importer import import_brief, import_briefs
from sensei_top.brief.narrative import NarrativeError
from sensei_top.db import open_database
from sensei_top.guide.authored import narrative_for, read_narrative, write_narrative
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.narrative import BoardCard, CardNote, GuideNarrative, MatchupPlan
from sensei_top.guide.plans import PlanProblem


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


def _corpus_deck(conn, event_id, archetype_key, archetype_name, mainboard):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES (?, 'p', 's', 'mtgo', 'e', '2026-08-15', "
        "'Standard', 'B')",
        (event_id,),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
        "losses) VALUES (?, 0, ?, '[]', 5, 0)",
        (event_id, json.dumps(mainboard)),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, 0, ?, ?, ?, 'archetype', 'now')",
        (event_id, archetype_key, archetype_name, archetype_name),
    )


def _identity() -> DeckIdentity:
    return DeckIdentity(
        key="guid:x", arena_deck_id="x", name="My Deck", format="Standard",
        deck_ids=("d1",), matches=5, match_wins=3, match_losses=2, games_won=6,
        games_lost=4, first_played="t", last_played="t",
        # 4x Opt maindeck, 2x Slagstorm sideboard
        current_cards={"maindeck": [10, 10, 10, 10], "sideboard": [11, 11]},
    )


def _seed(conn):
    _card(conn, 10, "Opt")
    _card(conn, 11, "Slagstorm")
    _card(conn, 1, "Marauding Mako")
    for i in range(6):
        _corpus_deck(conn, f"e{i}", "mardu_discard", "Mardu Discard",
                     [{"count": 4, "name": "Marauding Mako"}])
    conn.commit()


_VALID = {
    "prose": "They race you; trade early.",
    "play_around": [{"card": "Marauding Mako", "why": "grows on every discard"}],
    "board_in": [{"card": "Slagstorm", "n": 2}],
    "board_out": [{"card": "Opt", "n": 2}],
}


def test_import_brief_stores_a_written_answer(conn):
    _seed(conn)
    brief = import_brief(
        conn, _identity(), "mardu_discard", "Mardu Discard", json.dumps(_VALID),
        author="claude-code",
    )
    conn.commit()

    assert brief.prose == "They race you; trade early."
    assert brief.play_around[0].card == "Marauding Mako"
    assert brief.board_in == (BoardCard(card="Slagstorm", n=2),)
    assert brief.problems == ()  # balanced 2-for-2, both cards actually held

    back = store.read_brief(conn, "guid:x", "mardu_discard")
    assert back == brief
    # The evidence it was written from is stored beside it, so the prose can
    # always be checked against what its author was shown.
    assert "Marauding Mako" in back.prompt


def test_import_brief_records_a_broken_plan_rather_than_rejecting_it(conn):
    """guide/plans.py's standing rule: a plan the author got wrong is
    surfaced next to the matchup, never silently repaired — and never a
    reason to throw away prose that may still be worth reading."""
    _seed(conn)
    unbalanced = dict(_VALID, board_out=[{"card": "Opt", "n": 1}])
    brief = import_brief(
        conn, _identity(), "mardu_discard", "Mardu Discard", json.dumps(unbalanced),
        author="claude-code",
    )
    conn.commit()

    assert brief.prose  # stored anyway
    assert any("must swap equal numbers" in p.message for p in brief.problems)


def test_import_brief_catches_a_card_the_deck_does_not_hold(conn):
    _seed(conn)
    wrong = dict(_VALID, board_in=[{"card": "Ghost Vacuum", "n": 2}])
    brief = import_brief(
        conn, _identity(), "mardu_discard", "Mardu Discard", json.dumps(wrong),
        author="claude-code",
    )
    conn.commit()
    assert any("Ghost Vacuum" in p.message for p in brief.problems)


def test_import_brief_rejects_malformed_json(conn):
    _seed(conn)
    with pytest.raises(NarrativeError, match="not valid JSON"):
        import_brief(conn, _identity(), "mardu_discard", "Mardu Discard", "{oops",
                     author="x")


def test_import_brief_needs_a_field_consensus_to_anchor_to(conn):
    _card(conn, 10, "Opt")
    conn.commit()
    with pytest.raises(LookupError, match="no field consensus"):
        import_brief(conn, _identity(), "unknown_archetype", "Unknown", json.dumps(_VALID),
                     author="x")


# --- import_briefs (the multi-brief round trip) ------------------------------


def test_import_briefs_stores_one_row_per_archetype(conn):
    _seed(conn)
    for i in range(6):
        _corpus_deck(conn, f"f{i}", "izzet_control", "Izzet Control",
                     [{"count": 4, "name": "Marauding Mako"}])
    conn.commit()

    answer = {
        "briefs": [
            dict(_VALID, archetype_key="mardu_discard"),
            dict(_VALID, archetype_key="izzet_control", prose="Play around counters."),
        ]
    }
    stored, skipped = import_briefs(
        conn, _identity(), json.dumps(answer), author="claude-code",
        labels={"mardu_discard": "Mardu Discard", "izzet_control": "Izzet Control"},
    )
    conn.commit()

    assert skipped == []
    assert {b.archetype_key for b in stored} == {"mardu_discard", "izzet_control"}
    izzet = next(b for b in stored if b.archetype_key == "izzet_control")
    assert izzet.prose == "Play around counters."
    assert izzet.archetype_label == "Izzet Control"

    # Each stored row got its own single-brief context and facts — not a
    # slice of a shared multi-brief prompt.
    back = store.read_brief(conn, "guid:x", "mardu_discard")
    assert back is not None
    assert "Marauding Mako" in back.prompt


def test_import_briefs_collects_a_no_consensus_item_without_blocking_the_rest(conn):
    _seed(conn)
    conn.commit()

    answer = {
        "briefs": [
            dict(_VALID, archetype_key="mardu_discard"),
            dict(_VALID, archetype_key="unknown_archetype"),
        ]
    }
    stored, skipped = import_briefs(
        conn, _identity(), json.dumps(answer), author="claude-code",
    )
    conn.commit()

    assert [b.archetype_key for b in stored] == ["mardu_discard"]
    assert len(skipped) == 1
    assert skipped[0][0] == "unknown_archetype"
    assert "no field consensus" in skipped[0][1]


def test_import_briefs_falls_back_to_the_bare_key_with_no_label(conn):
    _seed(conn)
    conn.commit()
    answer = {"briefs": [dict(_VALID, archetype_key="mardu_discard")]}
    stored, _skipped = import_briefs(conn, _identity(), json.dumps(answer), author="x")
    conn.commit()
    assert stored[0].archetype_label == "mardu_discard"


def test_import_briefs_raises_before_writing_anything_on_malformed_json(conn):
    _seed(conn)
    conn.commit()
    answer = {"briefs": [dict(_VALID, archetype_key="mardu_discard"), {"archetype_key": "x"}]}
    with pytest.raises(NarrativeError):
        import_briefs(conn, _identity(), json.dumps(answer), author="x")
    conn.commit()
    assert store.briefs_for_deck(conn, "guid:x") == []


# --- the deck-level half -----------------------------------------------------


def _narrative() -> GuideNarrative:
    return GuideNarrative(
        engine="Cantrips are your mana.",
        fix="Deploy earlier.",
        card_notes=(CardNote("Opt", "correct", "cheap cantrip"),),
        matchups=(MatchupPlan("Mardu Discard", "Trade early.", (), ()),),
        checklist=("Am I casting cantrips on curve?",),
        problems=(PlanProblem("Mardu Discard", "example"),),
    )


def test_write_and_read_deck_narrative(conn):
    conn.commit()
    write_narrative(
        conn, "guid:x", _narrative(), list_hash="h1", prompt="the evidence",
        author="claude-code", corpus_commit="deadbeef",
    )
    conn.commit()

    stored = read_narrative(conn, "guid:x")
    assert stored.engine == "Cantrips are your mana."
    assert stored.card_notes[0].card == "Opt"
    assert stored.checklist == ("Am I casting cantrips on curve?",)
    assert stored.problems[0].message == "example"
    assert stored.author == "claude-code"
    assert stored.list_hash == "h1"


def test_reimporting_replaces_rather_than_duplicating(conn):
    conn.commit()
    for engine in ("first draft", "second draft"):
        write_narrative(
            conn, "guid:x", GuideNarrative(engine, "f", (), (), ()), list_hash="h1",
            prompt="p", author="a", corpus_commit=None,
        )
    conn.commit()
    assert read_narrative(conn, "guid:x").engine == "second draft"
    assert conn.execute("SELECT COUNT(*) FROM deck_narrative").fetchone()[0] == 1


def test_narrative_for_rehydrates_matchups_from_the_brief_table(conn):
    """Matchup plans live in matchup_brief, one place, shared with the live
    Current match tab — never duplicated into deck_narrative."""
    _seed(conn)
    import_brief(
        conn, _identity(), "mardu_discard", "Mardu Discard", json.dumps(_VALID),
        author="claude-code",
    )
    write_narrative(
        conn, "guid:x", _narrative(), list_hash="h1", prompt="p", author="a",
        corpus_commit=None,
    )
    conn.commit()

    stored, narrative = narrative_for(conn, "guid:x")
    assert stored.engine == "Cantrips are your mana."
    assert len(narrative.matchups) == 1
    assert narrative.matchups[0].archetype == "Mardu Discard"
    assert narrative.matchups[0].board_in == (BoardCard(card="Slagstorm", n=2),)


def test_narrative_for_is_none_when_nothing_was_imported(conn):
    conn.commit()
    assert narrative_for(conn, "guid:x") is None
