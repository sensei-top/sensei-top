"""Tests for brief/from_guide.py: backfilling the brief cache from a
generated deck guide's own matchup plans.
"""

from __future__ import annotations

import pytest

from sensei_top.brief import store
from sensei_top.brief.from_guide import store_guide_matchups
from sensei_top.db import open_database
from sensei_top.guide.bundle import DeckGuide, PlayEvidence, Provenance
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.field import ArchetypeShare, FieldEvidence, PersonalRate
from sensei_top.guide.narrative import BoardCard, GuideNarrative, MatchupPlan
from sensei_top.guide.plans import PlanProblem


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _archetype_row(conn, key, name):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier) VALUES ('e', 'p', 's', 'mtgo', 'e', '2026-08-15', "
        "'Standard', 'B')"
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
        "losses) VALUES ('e', 0, '[]', '[]', 5, 0)"
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES ('e', 0, ?, ?, ?, 'archetype', 'now')",
        (key, name, name),
    )


def _identity() -> DeckIdentity:
    return DeckIdentity(
        key="guid:x", arena_deck_id="x", name="My Deck", format="Standard",
        deck_ids=("d1",), matches=5, match_wins=3, match_losses=2, games_won=6,
        games_lost=4, first_played="t", last_played="t",
        current_cards={"maindeck": [1, 1, 1, 1], "sideboard": []},
    )


def _guide(
    identity: DeckIdentity, *, shares: tuple[ArchetypeShare, ...] = (),
    personal_rates: tuple[PersonalRate, ...] = (),
) -> DeckGuide:
    """A minimal DeckGuide carrying only what store_guide_matchups reads:
    the identity (via provenance.deck) and the field's shares/personal
    rates. Everything else is empty rather than exercised here."""
    return DeckGuide(
        provenance=Provenance(
            deck=identity, reset=None, window_start=None, matches_before_reset=0,
            corpus_fetched_at=None, corpus_latest_event=None, classified_decks=0,
            oracle_coverage=(0, 0),
        ),
        play=PlayEvidence(board_curve={}, zone_curve={}, key_card_timing={}, mulligan_record={},
                           game_length={}),
        leaks=(), leaks_all_decks=(), list_diff=None,
        field=FieldEvidence(
            fmt="Standard", window_start=None, classified_decks=0, shares=shares,
            changes={}, personal_rates=personal_rates, own_performance=None,
            corpus_fetched_at=None, corpus_latest_event=None,
        ),
        gaps=(),
    )


def _narrative(*matchups: MatchupPlan, problems=()) -> GuideNarrative:
    return GuideNarrative(
        engine="How it works.", fix="The fix.", card_notes=(), matchups=matchups,
        checklist=(), problems=problems,
    )


def test_stores_one_brief_per_resolvable_matchup(conn):
    _archetype_row(conn, "mardu_discard", "Mardu Discard")
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES ('e', 1, 'jeskai_control', 'Jeskai Control', "
        "'Jeskai Control', 'archetype', 'now')"
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
        "losses) VALUES ('e', 1, '[]', '[]', 5, 0)"
    )
    conn.commit()

    narrative = _narrative(
        MatchupPlan(
            archetype="Mardu Discard", prose="p1",
            board_in=(BoardCard("Slagstorm", 2),), board_out=(BoardCard("Get Out", 2),),
        ),
        MatchupPlan(
            archetype="Jeskai Control", prose="p2",
            board_in=(BoardCard("Flashfreeze", 1),), board_out=(BoardCard("Impractical Joke", 1),),
        ),
    )

    identity = _identity()
    guide = _guide(
        identity,
        shares=(ArchetypeShare(archetype="Mardu Discard", decks=10, share=0.2,
                                share_before_reset=None, movement=None),),
        personal_rates=(PersonalRate(archetype="Mardu Discard", matches=4, wins=3, losses=1,
                                      carryable=True),),
    )
    written = store_guide_matchups(conn, guide, narrative, model="claude-opus-5")
    conn.commit()
    assert written == 2

    b1 = store.read_brief(conn, "guid:x", "mardu_discard")
    assert b1 is not None
    assert b1.source == "guide"
    assert b1.prose == "p1"
    assert b1.archetype_share == pytest.approx(0.2)
    assert b1.personal_matches == 4
    assert b1.personal_wins == 3
    b2 = store.read_brief(conn, "guid:x", "jeskai_control")
    assert b2 is not None
    assert b2.prose == "p2"
    assert b2.archetype_share is None  # no share data for this archetype in the guide


def test_skips_an_archetype_name_that_does_not_resolve(conn):
    conn.commit()  # no meta_deck_archetype rows at all — nothing resolves

    narrative = _narrative(
        MatchupPlan(archetype="Some Unknown Deck", prose="p", board_in=(), board_out=()),
    )
    written = store_guide_matchups(conn, _guide(_identity()), narrative, model="claude-opus-5")
    conn.commit()
    assert written == 0
    assert store.briefs_for_deck(conn, "guid:x") == []


def test_does_not_overwrite_a_matching_live_brief(conn):
    _archetype_row(conn, "mardu_discard", "Mardu Discard")
    conn.commit()

    identity = _identity()
    hash_now = store.list_hash(identity.current_cards)
    live_brief = store.Brief(
        deck_key="guid:x", archetype_key="mardu_discard", archetype_label="Mardu Discard",
        archetype_share=None, personal_matches=None, personal_wins=None, personal_losses=None,
        prose="live prose, more targeted", play_around=(), board_in=(), board_out=(),
        staples=(), problems=(), prompt="p", model="claude-sonnet-5",
        generated_at="2026-08-20T00:00:00.000Z", corpus_commit=None, list_hash=hash_now,
        source="live",
    )
    store.write_brief(conn, live_brief)
    conn.commit()

    narrative = _narrative(
        MatchupPlan(archetype="Mardu Discard", prose="guide prose", board_in=(), board_out=()),
    )
    written = store_guide_matchups(conn, _guide(identity), narrative, model="claude-opus-5")
    conn.commit()

    assert written == 0
    still_live = store.read_brief(conn, "guid:x", "mardu_discard")
    assert still_live.source == "live"
    assert still_live.prose == "live prose, more targeted"


def test_carries_problems_scoped_to_their_own_archetype(conn):
    _archetype_row(conn, "mardu_discard", "Mardu Discard")
    conn.commit()

    narrative = _narrative(
        MatchupPlan(archetype="Mardu Discard", prose="p", board_in=(), board_out=()),
        problems=(PlanProblem(archetype="Mardu Discard", message="unbalanced"),),
    )
    store_guide_matchups(conn, _guide(_identity()), narrative, model="claude-opus-5")
    conn.commit()

    brief = store.read_brief(conn, "guid:x", "mardu_discard")
    assert brief.problems == (PlanProblem(archetype="Mardu Discard", message="unbalanced"),)


def test_a_shared_archetype_name_is_filed_under_its_majority_key(conn):
    """"Shared Midrange" labels 3 corpus decks under 'majority' and 1 under
    'minority' (inserted last). The plan lands under 'majority' — the same
    key guide/narrative.py chose its section with — not whichever row a
    DISTINCT lookup returned last."""
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier) VALUES ('e', 'p', 's', 'mtgo', 'e', '2026-08-15', 'Standard', 'B')"
    )
    for ord_, key in enumerate(["majority", "majority", "majority", "minority"]):
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, "
            "wins, losses) VALUES ('e', ?, '[]', '[]', 5, 0)",
            (ord_,),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) VALUES ('e', ?, ?, "
            "'Shared Midrange', 'Shared Midrange', 'archetype', 'now')",
            (ord_, key),
        )
    conn.commit()

    narrative = _narrative(MatchupPlan(
        archetype="Shared Midrange", prose="p", board_in=(), board_out=(),
    ))
    assert store_guide_matchups(conn, _guide(_identity()), narrative, model="m") == 1
    conn.commit()
    assert store.read_brief(conn, "guid:x", "majority") is not None
    assert store.read_brief(conn, "guid:x", "minority") is None


def test_briefs_carry_the_hash_the_guide_was_written_for(conn):
    """An imported guide answered for an older 75 (``answers.read_answer``'s
    ``context``) stores its briefs with that 75's hash, so they read as
    stale like the guide itself; none given is today's."""
    _archetype_row(conn, "mardu_discard", "Mardu Discard")
    conn.commit()
    identity = _identity()
    older = "ab" * 32
    narrative = _narrative(
        MatchupPlan(archetype="Mardu Discard", prose="p", board_in=(), board_out=()),
    )

    store_guide_matchups(conn, _guide(identity), narrative, model="m", list_hash=older)
    assert store.read_brief(conn, "guid:x", "mardu_discard").list_hash == older

    store_guide_matchups(conn, _guide(identity), narrative, model="m")
    assert (
        store.read_brief(conn, "guid:x", "mardu_discard").list_hash
        == store.list_hash(identity.current_cards)
    )


def test_an_older_hash_still_spares_a_live_brief_for_todays_list(conn):
    """The skip compares the live brief with today's 75, whatever list the
    guide was written for: a brief for this exact list is not replaced by a
    guide written for an older one."""
    _archetype_row(conn, "mardu_discard", "Mardu Discard")
    identity = _identity()
    store.write_brief(conn, store.Brief(
        deck_key="guid:x", archetype_key="mardu_discard", archetype_label="Mardu Discard",
        archetype_share=None, personal_matches=None, personal_wins=None, personal_losses=None,
        prose="live prose", play_around=(), board_in=(), board_out=(),
        staples=(), problems=(), prompt="p", model="m",
        generated_at="2026-08-20T00:00:00.000Z", corpus_commit=None,
        list_hash=store.list_hash(identity.current_cards), source="live",
    ))
    conn.commit()
    narrative = _narrative(
        MatchupPlan(archetype="Mardu Discard", prose="guide prose", board_in=(), board_out=()),
    )
    written = store_guide_matchups(
        conn, _guide(identity), narrative, model="m", list_hash="ab" * 32,
    )
    assert written == 0
    assert store.read_brief(conn, "guid:x", "mardu_discard").prose == "live prose"
