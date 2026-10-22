"""Tests for coach/evidence.py — the population every coach rollup shares,
and the first layer of rollups on top of it.

Every population here is built directly against the projected schema
(matches/games/decks/meta_*), the same synthetic-fixture precedent
tests/test_leaks.py already established for a piece that needs no full log
capture. Expected numbers are computed by hand from the rows each test
inserts, never from running build_coach_evidence and copying its output
(rule 8) — most test bodies say the arithmetic inline in a comment or
docstring so the expectation traces back to the fixture, not the code.
"""

from __future__ import annotations

import json
from collections import defaultdict
from types import SimpleNamespace

import pytest

import sensei_top.coach.evidence as evidence_mod
from sensei_top.archetypes.classify import Verdict
from sensei_top.brief.coverage import _field_counts
from sensei_top.coach.evidence import MIN_SAMPLE, build_coach_evidence
from sensei_top.db import open_database
from sensei_top.formats import arena_format
from sensei_top.guide.deck import DeckIdentity
from sensei_top.guide.play import mulligan_record
from sensei_top.review.analyzers.frame import analyze_frame
from sensei_top.review.consensus import ArchetypeConsensus, ConsensusCard
from sensei_top.review.findings import (
    Category,
    Confidence,
    Evidence,
    Finding,
    GameFacts,
    MatchReport,
    Severity,
)
from sensei_top.review.snapshot import MatchSnapshot, OwnCard


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


_FROM_EVENT = object()


def _insert_match(
    conn,
    match_id,
    result,
    *,
    event_id="Traditional_Ladder",
    deck_id=None,
    started_at="2026-01-01T00:00:00",
    source="arena",
    opponent_name="OppPlayerOne",
    opponent_user_id="OPPCLIENTID0001",
    games=None,
    fmt=_FROM_EVENT,
):
    """Mirrors tests/test_leaks.py's own ``_insert_match`` shape, extended
    with the fields this module's population/window logic actually branches
    on (``event_id`` NULL-ability, ``source``, ``started_at`` precision,
    opponent identity for the privacy test) rather than hard-coding them.

    ``matches.format`` is what the projector writes: for Arena,
    ``arena_format`` of the event with no deck format unless ``fmt`` says
    otherwise (the projector reads the deck's format too); MTGO's log names
    none, so an MTGO match's format comes from a pick or ``_infer``."""
    if fmt is _FROM_EVENT:
        fmt = arena_format(None, event_id) if source == "arena" else None
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason, source, format) VALUES (?, ?, ?, 1, 2, ?, ?, ?, ?, ?, "
        "1, 0, 'r', ?, ?)",
        (match_id, event_id, deck_id, opponent_user_id, opponent_name, started_at,
         started_at, result, source, fmt),
    )
    if games is None:
        games = [{"game_number": 1, "on_play": 1, "result": result, "self_mulligans": 0}]
    for g in games:
        conn.execute(
            "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
            "turn_count, self_mulligans, opp_mulligans) VALUES (?, ?, ?, ?, NULL, 6, ?, 0)",
            (match_id, g["game_number"], g.get("on_play"), g.get("result", result),
             g.get("self_mulligans")),
        )


def _insert_ban(conn, card_name="Bannedcard", event_date="2026-06-01", *, fmt="Standard",
                grp_id=1):
    """A minimal detectable ``fmt`` reset: one card banned in ``fmt``, last
    played (by two ``fmt`` decks — guide/window.py's own
    MIN_DECKS_FOR_LAST_APPEARANCE) on ``event_date``.
    guide/window.py::format_resets reads this and produces a FormatReset
    whose ``date`` is exactly ``event_date``, so ``window_start`` is the day
    after it."""
    event_id = f"ban-{fmt}"
    conn.execute(
        "INSERT INTO cards (grp_id, name) VALUES (?, ?)",
        (grp_id, card_name),
    )
    conn.execute(
        "INSERT INTO card_legality (grp_id, format, legality) VALUES (?, ?, 'banned')",
        (grp_id, fmt),
    )
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier, standings_rows) VALUES (?, 'p', 'sha', 'src', 'Event 1', ?, "
        "?, 'C', 0)",
        (event_id, event_date, fmt),
    )
    for deck_ord in (0, 1):
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, result, wins, losses, draws, "
            "mainboard_json, sideboard_json) VALUES (?, ?, '2-1', 2, 1, 0, ?, '[]')",
            (event_id, deck_ord, f'[{{"name": "{card_name}", "count": 4}}]'),
        )


# --- population gating and exclusions ---------------------------------------


def test_population_below_min_sample_returns_none(conn):
    for i in range(MIN_SAMPLE - 1):
        _insert_match(conn, f"m{i}", "win" if i % 2 == 0 else "loss")
    conn.commit()
    assert build_coach_evidence(conn, fmt="Standard") is None


def test_each_exclusion_reason_removes_the_match_and_reports_a_gap_line(conn):
    """10 good Constructed matches, plus one of each exclusion reason (a
    Limited queue, two DualColorPrecons matches, one with no event id at
    all) — population must stay at 10 and each reason must earn its own
    gap line with its own count."""
    for i in range(10):
        _insert_match(conn, f"good{i}", "win" if i % 2 == 0 else "loss")
    _insert_match(conn, "limited1", "win", event_id="QuickDraft_SOS_20260831")
    _insert_match(conn, "precon1", "win", event_id="DualColorPrecons")
    _insert_match(conn, "precon2", "loss", event_id="DualColorPrecons")
    _insert_match(conn, "noevent1", "win", event_id=None)
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10
    assert any(g.startswith("1 match(es) excluded") and "Limited queue" in g
               for g in evidence.gaps)
    assert any(g.startswith("2 match(es) excluded") and "excluded event" in g
               for g in evidence.gaps)
    assert (
        "1 Arena match(es) excluded: no event id was recorded, so the queue they were "
        "played in is unknown."
    ) in evidence.gaps


def test_a_pick_two_draft_event_is_limited(conn):
    """A real Arena id (the same one tests/test_table_queues.py carries)."""
    assert evidence_mod._is_limited_event("PickTwoDraft_FRA_20260929")
    _insert_match(conn, "pick2", "win", event_id="PickTwoDraft_FRA_20260929")
    conn.commit()
    pop, excluded = evidence_mod._population(conn, "all")
    assert pop == []
    assert excluded["limited"] == 1
    assert excluded["no_format"] == 0


def test_constructed_looking_event_ids_all_stay_in(conn):
    """Real event ids observed in the field, none of which _is_limited_event
    recognises as a Limited prefix and none of which is DualColorPrecons —
    every one of them must count toward the population, not be silently
    dropped by an over-eager exclusion. Each is played with a Standard deck,
    so the projector's ``arena_format("Standard", event_id)`` gives every
    one a format."""
    for i, event_id in enumerate(
        ["Play", "Traditional_Ladder", "Traditional_Cons_Event_2026", "Constructed_BestOf3"]
    ):
        for j in range(3):
            _insert_match(conn, f"m{i}_{j}", "win" if j == 0 else "loss", event_id=event_id,
                          fmt=arena_format("Standard", event_id))
    conn.commit()
    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 12
    # No match here was excluded by any population rule -- the gaps that do
    # appear (no legality data / no classified opponents) are about the
    # format window and by_opponent, not about the population, so they are
    # expected: this fixture never sets up legality or opponent archetype
    # data at all.
    assert not any("match(es) excluded" in g for g in evidence.gaps)


def test_a_match_with_no_format_is_excluded_not_guessed(conn):
    """10 ladder matches (Standard from the event) plus two unranked "Play"
    matches whose deck names no format: ``arena_format(None, "Play")`` is
    None, so neither may be counted under a guessed format (rule 4)."""
    for i in range(10):
        _insert_match(conn, f"good{i}", "win" if i % 2 == 0 else "loss")
    _insert_match(conn, "play0", "win", event_id="Play")
    _insert_match(conn, "play1", "loss", event_id="Play")
    conn.commit()

    pop, excluded = evidence_mod._population(conn, "all")
    assert {m.match_id for m in pop} == {f"good{i}" for i in range(10)}
    assert excluded["no_format"] == 2

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10
    assert (
        "2 match(es) excluded: none of the seven formats this app tracks is known for them "
        "(an Arena queue for another format, or an MTGO match with no confirmed or inferred "
        "format)."
    ) in evidence.gaps


# --- MTGO population: inclusion, per-reason exclusion, by_source -------------
#
# MTGO writes no event_id and no format, so an MTGO match's format is the
# user's pick (mtgo_match_pick.format) or, without one, the format
# archetypes/classify.py::infer_formats read from its revealed cards, stored
# in match_format_inference -- both read through v_match_format. Its
# matches.deck_id is NULL too: its decks rows come from deck files, reached
# only through the user's pick. The inference itself is tested in
# tests/test_match_formats.py; here its stored verdict is seeded directly.


def _infer(conn, match_id, fmt, reason="fit"):
    """One match_format_inference row, as classify_matches writes it:
    ``format`` is set only when ``reason`` is ``fit`` (migration 056)."""
    conn.execute(
        "INSERT INTO match_format_inference (match_id, format, reason) VALUES (?, ?, ?)",
        (match_id, fmt, reason),
    )


def _insert_mtgo_match(conn, match_id, result, *, started_at="2026-08-01T00:00:00"):
    _insert_match(conn, match_id, result, source="mtgo", event_id=None, started_at=started_at)


def test_mtgo_match_with_an_inferred_format_is_included_but_never_reaches_by_deck(conn):
    """9 good Arena matches plus one MTGO match its revealed cards fit to
    Standard: population must reach 10 (MIN_SAMPLE), by_source must split 9
    Arena / 1 MTGO, and the by_deck gap line documenting the MTGO match's
    absence from by_deck must appear -- MTGO writes no deck_id, no pick was
    made, and none is invented."""
    for i in range(9):
        _insert_match(conn, f"good{i}", "win" if i % 2 == 0 else "loss")
    _insert_mtgo_match(conn, "mtgo1", "win")
    _infer(conn, "mtgo1", "Standard")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10
    assert evidence.by_source["arena"].n == 9
    assert evidence.by_source["mtgo"].n == 1
    assert evidence.by_source["mtgo"].wins == 1
    assert not any("match(es) excluded" in g for g in evidence.gaps)
    assert any(
        g.startswith("1 MTGO match(es) are counted") and "no per-deck line" in g
        for g in evidence.gaps
    )


def _seed_mtgo_population(conn):
    """9 Arena matches and one MTGO match inferred Standard (``mtgo1``, a
    win), plus a Standard ``decks`` row for an MTGO deck file. Nothing is
    picked."""
    for i in range(9):
        _insert_match(conn, f"good{i}", "win" if i % 2 == 0 else "loss")
    _insert_mtgo_match(conn, "mtgo1", "win")
    _infer(conn, "mtgo1", "Standard")
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('mtgodeck', 'Picked MTGO Deck', 'Standard', '{}', 't', 't')"
    )
    conn.commit()


def test_mtgo_match_with_a_picked_deck_counts_under_that_deck(conn):
    """The pick is the only source of an MTGO match's deck (v_match_deck), so
    with one the match leaves the no-per-deck gap and is a line of its own;
    the one match and its one win are the seeded ones."""
    _seed_mtgo_population(conn)
    conn.execute("INSERT INTO mtgo_match_pick (match_id, deck_id) VALUES ('mtgo1', 'mtgodeck')")
    conn.commit()

    pop, _excluded = evidence_mod._population(conn, "all")
    assert {m.match_id: m.deck_id for m in pop}["mtgo1"] == "mtgodeck"

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.by_source["mtgo"].n == 1
    lines = {line.label: line for line in evidence.by_deck}
    assert (lines["Picked MTGO Deck"].matches.wins, lines["Picked MTGO Deck"].matches.n) == (1, 1)
    assert not any("no per-deck line" in g for g in evidence.gaps)


def test_own_archetype_of_a_picked_mtgo_deck_reads_through_the_pick(conn, monkeypatch):
    """_own_archetype finds the deck's most recent match through v_match_deck:
    the only match carrying 'mtgodeck' is the picked MTGO one, so a stand-in
    verdict for exactly that deck must reach its DeckLine."""
    _seed_mtgo_population(conn)
    conn.execute("INSERT INTO mtgo_match_pick (match_id, deck_id) VALUES ('mtgo1', 'mtgodeck')")
    conn.commit()

    def fake_classify(_conn, deck_id, _event_id, **_kwargs):
        verdict = SimpleNamespace(name="Test Archetype") if deck_id == "mtgodeck" else None
        return verdict, ()

    monkeypatch.setattr(evidence_mod, "classify_own_deck", fake_classify)

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    lines = {line.label: line for line in evidence.by_deck}
    assert lines["Picked MTGO Deck"].archetype == "Test Archetype"


def test_mtgo_match_without_a_picked_deck_stays_in_no_deck_line(conn):
    """A pick that confirms only the format leaves the match deckless, same as
    no pick at all: the deck is never guessed."""
    _seed_mtgo_population(conn)
    conn.execute("INSERT INTO mtgo_match_pick (match_id, format) VALUES ('mtgo1', 'Standard')")
    conn.commit()

    pop, _excluded = evidence_mod._population(conn, "all")
    assert {m.match_id: m.deck_id for m in pop}["mtgo1"] is None

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert all(line.label != "Picked MTGO Deck" for line in evidence.by_deck)
    assert any(
        g.startswith("1 MTGO match(es) are counted") and "no per-deck line" in g
        for g in evidence.gaps
    )


def test_a_pick_never_overrides_the_deck_an_arena_match_names(conn):
    """v_match_deck joins the pick to MTGO matches only: a stray row for an
    Arena match id changes nothing."""
    _seed_mtgo_population(conn)
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('arenadeck', 'Arena Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute("UPDATE matches SET deck_id = 'arenadeck' WHERE match_id = 'good0'")
    conn.execute("INSERT INTO mtgo_match_pick (match_id, deck_id) VALUES ('good0', 'mtgodeck')")
    conn.commit()

    pop, _excluded = evidence_mod._population(conn, "all")
    assert {m.match_id: m.deck_id for m in pop}["good0"] == "arenadeck"


def test_a_confirmed_pick_keeps_a_match_the_inference_excludes(conn):
    """The inference found no format this match's cards fit (``no_fit``);
    the user's confirmed Standard is the better evidence (v_match_format
    reads the pick first), so it counts and earns no exclusion gap."""
    for i in range(9):
        _insert_match(conn, f"good{i}", "win" if i % 2 == 0 else "loss")
    _insert_mtgo_match(conn, "mtgo_nf", "win")
    _infer(conn, "mtgo_nf", None, "no_fit")
    conn.execute("INSERT INTO mtgo_match_pick (match_id, format) VALUES ('mtgo_nf', 'Standard')")
    conn.commit()

    pop, excluded = evidence_mod._population(conn, "all")
    assert {m.match_id: m.format for m in pop}["mtgo_nf"] == "Standard"
    assert not any(excluded.values())

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10
    assert evidence.by_source["mtgo"].n == 1
    assert not any("match(es) excluded" in g for g in evidence.gaps)


def test_a_confirmed_other_format_keeps_the_match_under_that_format(conn):
    """A match inferred Standard that the user confirmed as Modern is in the
    population as a Modern match: skill evidence counts it, Standard's
    format sections do not, and nothing is excluded."""
    _seed_mtgo_population(conn)
    conn.execute("INSERT INTO mtgo_match_pick (match_id, format) VALUES ('mtgo1', 'Modern')")
    conn.commit()

    pop, excluded = evidence_mod._population(conn, "all")
    assert {m.match_id: m.format for m in pop}["mtgo1"] == "Modern"
    assert not any(excluded.values())

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10
    assert evidence.by_source["mtgo"].n == 1
    # 9 Arena ladder matches are Standard; no reset, so all of them.
    assert evidence.format_population == 9
    assert evidence.format_counts == (("Standard", 9), ("Modern", 1))


def test_a_deck_only_pick_leaves_the_inference_standing(conn):
    """A pick with no format answers nothing about the format: the
    inference's ``no_fit`` still excludes the match."""
    for i in range(10):
        _insert_match(conn, f"good{i}", "win" if i % 2 == 0 else "loss")
    _insert_mtgo_match(conn, "mtgo_nf", "win")
    _infer(conn, "mtgo_nf", None, "no_fit")
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('mtgodeck', 'Picked MTGO Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute("INSERT INTO mtgo_match_pick (match_id, deck_id) VALUES ('mtgo_nf', 'mtgodeck')")
    conn.commit()

    pop, excluded = evidence_mod._population(conn, "all")
    assert "mtgo_nf" not in {m.match_id for m in pop}
    assert excluded["no_fit"] == 1


def test_a_pick_format_never_moves_an_arena_match(conn):
    """v_match_deck applies a pick to MTGO matches only, so a stray row naming
    another format for an Arena match id leaves it a Standard match."""
    _seed_mtgo_population(conn)
    conn.execute("INSERT INTO mtgo_match_pick (match_id, format) VALUES ('good0', 'Modern')")
    conn.commit()

    pop, _excluded = evidence_mod._population(conn, "all")
    assert {m.match_id: m.format for m in pop}["good0"] == "Standard"


def test_each_inference_reason_removes_the_match_and_reports_a_gap_line(conn):
    """10 good Arena matches, plus one MTGO match for each reason
    match_format_inference gives a match it found no format for, and one
    MTGO match never inferred at all (no row: ``no_format``). Population
    must stay at 10 -- none of the six count -- and each reason earns its
    own gap line with its own count."""
    for i in range(10):
        _insert_match(conn, f"good{i}", "win" if i % 2 == 0 else "loss")
    reasons = ("unresolved_cards", "unknown_legality", "no_fit", "too_few_cards", "ambiguous")
    for reason in reasons:
        _insert_mtgo_match(conn, f"mtgo_{reason}", "win")
        _infer(conn, f"mtgo_{reason}", None, reason)
    _insert_mtgo_match(conn, "mtgo_never_inferred", "win")
    conn.commit()

    pop, excluded = evidence_mod._population(conn, "all")
    assert len(pop) == 10
    assert {reason: excluded[reason] for reason in (*reasons, "no_format")} == dict.fromkeys(
        (*reasons, "no_format"), 1
    )

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10
    assert evidence.by_source["mtgo"].n == 0
    for phrase in (
        "revealed a card the local card database could not name, so its legality can't be "
        "read.",
        "no legality on file",
        "no one of the seven formats this app tracks allows every card they revealed.",
        "too few distinct",
        "the revealed cards fit two or more formats, neither inside the other, and only a "
        "confirmed format can tell which.",
    ):
        matching = [g for g in evidence.gaps if phrase in g]
        assert len(matching) == 1, phrase
        assert matching[0].startswith("1 MTGO match(es) excluded"), phrase
    assert any(
        g.startswith("1 match(es) excluded: none of the seven formats this app tracks")
        for g in evidence.gaps
    )
    # No MTGO match made it into the population, so the by_deck gap line
    # (which only fires when by_source["mtgo"].n is nonzero) must not appear.
    assert not any("no per-deck line" in g for g in evidence.gaps)


# --- one format's report: format sections vs. skill sections ----------------
#
# Standard: 10 Arena ladder matches with "Standard Deck" (decks.format
#   Standard), 2026-07-01, s0-s5 won, s6-s9 lost -> 6-4. Every opponent
#   classified Boros Aggro (in Standard).
# Modern: 11 MTGO matches picked "Modern Deck" (decks.format Modern) with
#   the format confirmed as Modern. A card banned in Modern was last played
#   on 2026-08-01, so Modern's window starts 2026-08-02. mold (2026-07-01,
#   won) predates it; d0-d9 (2026-08-15) are in it, d0-d2 won, d3-d9 lost
#   -> 3-7. Every opponent classified Amulet Titan (in Modern).
# A card banned in Standard was last played on 2026-06-01, so Standard's
#   window starts 2026-06-02: every s match is in it.
# Field: one Amulet Titan deck in a Modern event on 2026-08-20, one Boros
#   Aggro deck in a Standard event on 2026-08-25.
# Each match's report, snapshot and leak reading is measured against its
#   own format's window, whichever format the report is for: Modern's
#   2026-08-02 for mold and d0-d9 (mold too: the window is its format's, not
#   a date filter on the match), Standard's 2026-06-02 for s0-s9.
# Every match has one game, game 1, on the play, kept at seven; every
#   report casts the player as the beatdown. Two losses, d3 and s6, have
#   turns rows, so both are example games.
#
# Skill sections, either format: 21 matches, 6 + 3 + 1 = 10 wins; 21 game
#   ones on the play, 10 won; 21 kept sevens; Arena 10 (6 wins), MTGO 11
#   (4 wins).
# Modern's format sections: d0-d9 only (mold is before the window) -> 10
#   matches, 3-7, for Modern Deck, beatdown and Amulet Titan alike.
# Standard's: s0-s9 -> 10 matches, 6-4.


def _seed_two_formats(conn):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('stddeck', 'Standard Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('moddeck', 'Modern Deck', 'Modern', '{}', 't', 't')"
    )
    for i in range(10):
        mid = f"s{i}"
        _insert_match(conn, mid, "win" if i < 6 else "loss", deck_id="stddeck",
                      started_at="2026-07-01T00:00:00")
        _insert_auto_classification(conn, mid, "boros-aggro", "Boros Aggro")
    modern = [("mold", "win", "2026-07-01T00:00:00")] + [
        (f"d{i}", "win" if i < 3 else "loss", "2026-08-15T00:00:00") for i in range(10)
    ]
    for mid, result, started_at in modern:
        _insert_mtgo_match(conn, mid, result, started_at=started_at)
        conn.execute(
            "INSERT INTO mtgo_match_pick (match_id, deck_id, format) "
            "VALUES (?, 'moddeck', 'Modern')",
            (mid,),
        )
        _insert_auto_classification(conn, mid, "amulet-titan", "Amulet Titan", fmt="Modern")
    _insert_ban(conn, "Modern Bannedcard", "2026-08-01", fmt="Modern", grp_id=2)
    _insert_ban(conn, "Standard Bannedcard", "2026-06-01")
    for mid in ("d3", "s6"):
        _insert_self_turns(conn, mid, self_lands_by_turn=[(1, 1), (2, 2), (3, 3)])
    _insert_field_deck(conn, "modern-ev", 0, "amulet-titan", "Amulet Titan", "2026-08-20",
                       fmt="Modern")
    _insert_field_deck(conn, "standard-ev", 0, "boros-aggro", "Boros Aggro", "2026-08-25")
    conn.commit()


_TWO_FORMAT_WINDOWS = {"Modern": "2026-08-02", "Standard": "2026-06-02"}
_TWO_FORMAT_MATCHES = {
    **{f"s{i}": "Standard" for i in range(10)},
    "mold": "Modern",
    **{f"d{i}": "Modern" for i in range(10)},
}


def _beatdown_reports_recording_windows(monkeypatch):
    """Every report is a beatdown one; every window a report, snapshot or
    leak reading is given is recorded: per match for reports and snapshots,
    per format asked of the resolver find_leaks receives."""
    seen = {"report": defaultdict(set), "snapshot": defaultdict(set), "leaks": set()}

    def report(conn, match_id, *, consensus_since=None, **_kwargs):
        seen["report"][match_id].add(consensus_since)
        result = conn.execute(
            "SELECT result FROM matches WHERE match_id = ?", (match_id,)
        ).fetchone()["result"]
        return _role_report(match_id, result, "beatdown")

    real_build_snapshot = evidence_mod.build_snapshot

    def snapshot(conn, match_id, *, consensus_since=None, **kwargs):
        seen["snapshot"][match_id].add(consensus_since)
        return real_build_snapshot(conn, match_id, consensus_since=consensus_since, **kwargs)

    real_find_leaks = evidence_mod.find_leaks

    def leaks(conn, *, consensus_window, **kwargs):
        def recording_window(fmt):
            window = consensus_window(fmt)
            seen["leaks"].add((fmt, window))
            return window

        return real_find_leaks(conn, consensus_window=recording_window, **kwargs)

    monkeypatch.setattr(evidence_mod, "build_match_report", report)
    monkeypatch.setattr(evidence_mod, "build_snapshot", snapshot)
    monkeypatch.setattr(evidence_mod, "find_leaks", leaks)
    return seen


def _assert_each_match_got_its_own_formats_window(seen):
    assert dict(seen["report"]) == {
        mid: {_TWO_FORMAT_WINDOWS[f]} for mid, f in _TWO_FORMAT_MATCHES.items()
    }
    assert dict(seen["snapshot"]) == {"d3": {"2026-08-02"}, "s6": {"2026-06-02"}}
    assert seen["leaks"] == set(_TWO_FORMAT_WINDOWS.items())


def _assert_skill_sections_span_both_formats(evidence):
    assert evidence.population == 21
    assert (evidence.overall.wins, evidence.overall.n) == (10, 21)
    assert evidence.mulligans["kept_seven"].n == 21
    assert (evidence.by_source["arena"].wins, evidence.by_source["arena"].n) == (6, 10)
    assert (evidence.by_source["mtgo"].wins, evidence.by_source["mtgo"].n) == (4, 11)
    assert (evidence.g1.wins, evidence.g1.n) == (10, 21)
    assert (evidence.on_play.wins, evidence.on_play.n) == (10, 21)
    assert evidence.format_counts == (("Modern", 11), ("Standard", 10))


def test_a_modern_match_is_format_evidence_for_modern_only(conn, monkeypatch):
    _seed_two_formats(conn)
    seen = _beatdown_reports_recording_windows(monkeypatch)

    modern = build_coach_evidence(conn, fmt="Modern")
    assert modern is not None
    assert modern.fmt == "Modern"
    _assert_each_match_got_its_own_formats_window(seen)
    _assert_skill_sections_span_both_formats(modern)
    assert modern.window_start == "2026-08-02"
    assert modern.format_population == 10
    assert [(d.label, d.matches.wins, d.matches.n) for d in modern.by_deck] == [
        ("Modern Deck", 3, 10)
    ]
    assert {role: (r.wins, r.n) for role, r in modern.by_role.items()} == {"beatdown": (3, 10)}
    assert [(o.archetype, o.rate.wins, o.rate.n) for o in modern.by_opponent] == [
        ("Amulet Titan", 3, 10)
    ]
    assert [line.archetype for line in modern.field] == ["Amulet Titan"]
    assert modern.field_latest_event == "2026-08-20"

    for record in seen.values():
        record.clear()
    standard = build_coach_evidence(conn, fmt="Standard")
    assert standard is not None
    assert standard.fmt == "Standard"
    _assert_each_match_got_its_own_formats_window(seen)
    _assert_skill_sections_span_both_formats(standard)
    assert standard.window_start == "2026-06-02"
    assert standard.format_population == 10
    assert [(d.label, d.matches.wins, d.matches.n) for d in standard.by_deck] == [
        ("Standard Deck", 6, 10)
    ]
    assert {role: (r.wins, r.n) for role, r in standard.by_role.items()} == {"beatdown": (6, 10)}
    assert [(o.archetype, o.rate.wins, o.rate.n) for o in standard.by_opponent] == [
        ("Boros Aggro", 6, 10)
    ]
    assert [line.archetype for line in standard.field] == ["Boros Aggro"]
    assert standard.field_latest_event == "2026-08-25"


def test_fmt_matches_played_with_another_formats_deck_are_a_by_deck_gap(conn):
    """10 Arena ladder matches with a Standard deck, plus 3 MTGO matches the
    user confirmed as Standard but played with a deck whose own format
    (decks.format) is Modern. The 3 count among Standard's 13 format
    matches, but the Modern deck gets no Standard per-deck line, and the gap
    says so."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('stddeck', 'Standard Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('moddeck', 'Modern Deck', 'Modern', '{}', 't', 't')"
    )
    for i in range(10):
        _insert_match(conn, f"s{i}", "win" if i % 2 == 0 else "loss", deck_id="stddeck")
    for i in range(3):
        _insert_mtgo_match(conn, f"x{i}", "win")
        conn.execute(
            "INSERT INTO mtgo_match_pick (match_id, deck_id, format) "
            "VALUES (?, 'moddeck', 'Standard')",
            (f"x{i}",),
        )
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.format_population == 13
    assert [(d.label, d.matches.n) for d in evidence.by_deck] == [("Standard Deck", 10)]
    assert (
        "3 Standard match(es) were played with a deck whose own format is another one, "
        "so they count in the Standard records but in no per-deck line."
    ) in evidence.gaps


def test_a_format_with_no_matches_in_its_window_still_builds_with_a_gap(conn):
    """10 Standard ladder matches and a Modern ban last played 2026-08-01,
    so Modern's window starts 2026-08-02 and holds no match at all. The
    skill population (10) clears MIN_SAMPLE, so a Modern report is still
    built: its format sections are empty, and the gap says so."""
    for i in range(10):
        _insert_match(conn, f"s{i}", "win" if i % 2 == 0 else "loss")
    _insert_ban(conn, "Modern Bannedcard", "2026-08-01", fmt="Modern")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Modern")
    assert evidence is not None
    assert evidence.population == 10
    assert evidence.format_population == 0
    assert evidence.window_start == "2026-08-02"
    assert (evidence.by_deck, evidence.by_role, evidence.by_opponent, evidence.decklists) == (
        (), {}, (), ()
    )
    assert (
        "No Modern matches since 2026-08-02 (the last Modern format change): the per-deck, "
        "per-role and per-opponent records and the decklists are empty. The skill sections "
        "still cover every format played, and the field section still shows the Modern field."
    ) in evidence.gaps


def test_a_format_never_played_with_no_reset_gets_the_no_window_gap(conn):
    """10 Standard ladder matches and nothing about Pioneer at all: no
    Pioneer match, no Pioneer reset."""
    for i in range(10):
        _insert_match(conn, f"s{i}", "win" if i % 2 == 0 else "loss")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Pioneer")
    assert evidence is not None
    assert evidence.format_population == 0
    assert evidence.window_start is None
    assert (
        "No Pioneer matches on file: the per-deck, per-role and per-opponent records and the "
        "decklists are empty. The skill sections still cover every format played, and the "
        "field section still shows the Pioneer field."
    ) in evidence.gaps
    assert not any(g.startswith("No Pioneer matches since") for g in evidence.gaps)


# --- overall / overall_games / by_deck --------------------------------------


# Ten matches, one deck ("deckA"), hand-built game-by-game so every rollup
# below can be checked against arithmetic done on this table alone:
#
#   match  result  g1(on_play,result)      g2(on_play,result)   g3(on_play,result)
#   m0     win     (1, win)                (0, win)
#   m1     win     (1, loss)               (0, win)
#   m2     loss    (0, loss)               (1, loss)
#   m3     win     (0, win)                (1, win)
#   m4     loss    (1, loss)
#   m5     win     (0, win)
#   m6     loss    (1, win)                (0, loss)             (1, loss)
#   m7     win     (0, loss)               (1, win)              (0, win)
#   m8     loss    (1, loss)               (0, loss)
#   m9     win     (0, win)                (1, win)
#
# matches: 6 wins / 10                                   -> overall
# all 20 games: 11 wins / 20                              -> overall_games
# game_number==1 (10 games): win,loss,loss,win,loss,win,win,loss,loss,win
#   = 5 wins / 10                                         -> g1
# game_number>=2 (10 games): win,win,loss,win,loss,loss,win,win,loss,win
#   = 6 wins / 10                                         -> post_board
# on_play==1 (10 games): m0g1(w) m1g1(l) m2g2(l) m3g2(w) m4g1(l) m6g1(w)
#   m6g3(l) m7g2(w) m8g1(l) m9g2(w) = 5 wins / 10          -> on_play
# on_play==0 (10 games): m0g2(w) m1g2(w) m2g1(l) m3g1(w) m5g1(w) m6g2(l)
#   m7g1(l) m7g3(w) m8g2(l) m9g1(w) = 6 wins / 10          -> on_draw
_DECK_MATCHES = [
    ("m0", "win", [(1, 1, "win"), (2, 0, "win")]),
    ("m1", "win", [(1, 1, "loss"), (2, 0, "win")]),
    ("m2", "loss", [(1, 0, "loss"), (2, 1, "loss")]),
    ("m3", "win", [(1, 0, "win"), (2, 1, "win")]),
    ("m4", "loss", [(1, 1, "loss")]),
    ("m5", "win", [(1, 0, "win")]),
    ("m6", "loss", [(1, 1, "win"), (2, 0, "loss"), (3, 1, "loss")]),
    ("m7", "win", [(1, 0, "loss"), (2, 1, "win"), (3, 0, "win")]),
    ("m8", "loss", [(1, 1, "loss"), (2, 0, "loss")]),
    ("m9", "win", [(1, 0, "win"), (2, 1, "win")]),
]


def test_overall_and_deck_level_rates_from_a_ten_match_population(conn):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckA', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    for match_id, result, games in _DECK_MATCHES:
        _insert_match(
            conn, match_id, result, deck_id="deckA",
            games=[{"game_number": gn, "on_play": op, "result": r} for gn, op, r in games],
        )
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10

    assert evidence.overall.wins == 6
    assert evidence.overall.n == 10

    assert evidence.overall_games.wins == 11
    assert evidence.overall_games.n == 20

    assert len(evidence.by_deck) == 1
    line = evidence.by_deck[0]
    assert line.label == "My Deck"
    # cards_json is '{}' (no maindeck) -> classify_own_deck bails out before
    # ever reaching the archetype rules, so this deck is correctly None, not
    # a guess.
    assert line.archetype is None
    assert (line.matches.wins, line.matches.n) == (6, 10)
    assert (line.g1.wins, line.g1.n) == (5, 10)
    assert (line.post_board.wins, line.post_board.n) == (6, 10)
    assert (line.on_play.wins, line.on_play.n) == (5, 10)
    assert (line.on_draw.wins, line.on_draw.n) == (6, 10)


def test_by_deck_overflow_beyond_top_n_is_a_gap_not_silent_truncation(conn):
    """9 decks with population matches; only the top 8 by match count may
    appear, and the 9th (fewest matches) must be named in a gap line
    instead of silently vanishing."""
    for d in range(9):
        deck_id = f"deck{d}"
        conn.execute(
            "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
            "VALUES (?, ?, 'Standard', '{}', 't', 't')",
            (deck_id, f"Deck {d}"),
        )
        # deck0 gets 1 match (the smallest), deck1..deck8 get 2 each -- 9
        # decks * >=1 match = well above MIN_SAMPLE, and deck0 is
        # unambiguously last by count.
        n_matches = 1 if d == 0 else 2
        for i in range(n_matches):
            _insert_match(conn, f"m{d}_{i}", "win", deck_id=deck_id)
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert len(evidence.by_deck) == 8
    assert all(line.label != "Deck 0" for line in evidence.by_deck)
    assert any("1 deck(s) beyond the top 8" in g for g in evidence.gaps)


# --- by_role, including "unknown" -------------------------------------------


def _role_report(match_id: str, result: str, role: str | None) -> MatchReport:
    findings: tuple[Finding, ...] = ()
    if role is not None:
        findings = (Finding(
            code="role_assignment", analyzer="frame", category=Category.FRAME,
            severity=Severity.NOTE, confidence=Confidence.PARTIAL,
            title="irrelevant", detail="irrelevant",
            evidence=(Evidence("role", "Role this matchup assigns", role),),
        ),)
    return MatchReport(match_id=match_id, deck_id=None, result=result, findings=findings)


def test_by_role_buckets_every_population_match_including_unknown(conn, monkeypatch):
    # 4 beatdown (3W/1L), 4 control (2W/2L), 2 mixed (1W/1L), 2 with no
    # role_assignment finding at all (1W/1L) -> "unknown".
    plan = (
        [(f"beat{i}", "win" if i < 3 else "loss", "beatdown") for i in range(4)]
        + [(f"ctrl{i}", "win" if i < 2 else "loss", "control") for i in range(4)]
        + [(f"mix{i}", "win" if i < 1 else "loss", "mixed") for i in range(2)]
        + [(f"unk{i}", "win" if i < 1 else "loss", None) for i in range(2)]
    )
    reports: dict[str, MatchReport] = {}
    for match_id, result, role in plan:
        _insert_match(conn, match_id, result)
        reports[match_id] = _role_report(match_id, result, role)
    conn.commit()

    monkeypatch.setattr(
        evidence_mod, "build_match_report",
        lambda conn, match_id, **kwargs: reports[match_id],
    )

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert (evidence.by_role["beatdown"].wins, evidence.by_role["beatdown"].n) == (3, 4)
    assert (evidence.by_role["control"].wins, evidence.by_role["control"].n) == (2, 4)
    assert (evidence.by_role["mixed"].wins, evidence.by_role["mixed"].n) == (1, 2)
    assert (evidence.by_role["unknown"].wins, evidence.by_role["unknown"].n) == (1, 2)


# --- mulligans ---------------------------------------------------------------


def test_mulligans_kept_seven_vs_mulliganed_excludes_null_games(conn):
    # 4 kept at seven (2W/2L), 4 mulliganed (2W/2L), 2 with self_mulligans
    # never observed -- excluded from both buckets, same as
    # guide/play.py::mulligan_record's own NULL handling.
    plan = [
        (0, "win"), (0, "loss"), (0, "win"), (0, "loss"),
        (1, "win"), (1, "loss"), (2, "win"), (2, "loss"),
        (None, "win"), (None, "loss"),
    ]
    for i, (mulls, result) in enumerate(plan):
        _insert_match(
            conn, f"m{i}", result,
            games=[{"game_number": 1, "on_play": 1, "result": result, "self_mulligans": mulls}],
        )
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert (evidence.mulligans["kept_seven"].wins, evidence.mulligans["kept_seven"].n) == (2, 4)
    assert (evidence.mulligans["mulliganed"].wins, evidence.mulligans["mulliganed"].n) == (2, 4)


def test_mulligan_record_and_build_mulligans_agree_over_the_same_matches(conn):
    """``guide/play.py::mulligan_record`` (one deck identity's own
    ``deck_ids``) and ``_build_mulligans`` (a report's own match population)
    both now call ``guide/play.py::mulligan_split`` -- pinned here by
    comparing their output over the exact same match ids.

    3 kept at seven (2W/1L), 3 mulliganed (1W/2L)."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckhash1', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    plan = [
        (0, "win"), (0, "win"), (0, "loss"),
        (1, "win"), (2, "loss"), (1, "loss"),
    ]
    match_ids = tuple(f"pm{i}" for i in range(len(plan)))
    for match_id, (mulls, result) in zip(match_ids, plan, strict=True):
        _insert_match(
            conn, match_id, result, deck_id="deckhash1",
            games=[{"game_number": 1, "on_play": 1, "result": result, "self_mulligans": mulls}],
        )
    conn.commit()

    identity = _identity(deck_ids=("deckhash1",))
    from_identity = mulligan_record(conn, identity)
    from_population = evidence_mod._build_mulligans(conn, match_ids)

    assert (from_identity["kept_seven"].wins, from_identity["kept_seven"].games) == (2, 3)
    assert (from_identity["mulliganed"].wins, from_identity["mulliganed"].games) == (1, 3)
    assert (from_population["kept_seven"].wins, from_population["kept_seven"].n) == (2, 3)
    assert (from_population["mulliganed"].wins, from_population["mulliganed"].n) == (1, 3)


# --- by_opponent and the format window --------------------------------------


def _insert_auto_classification(conn, match_id, archetype_key, label, *, fmt="Standard"):
    """A row as ``archetypes.classify``'s rule engine would have written it
    -- ``method='archetype'`` (rather than the two other CHECK-allowed
    values, ``fallback``/``corpus``, which this module's own by_opponent
    query never distinguishes between) with a matching ``label`` and
    ``archetype_name``, under ``fmt`` (v_match_opponent reads the row of
    the match's own format)."""
    conn.execute(
        "INSERT INTO opponent_archetype (match_id, format, archetype_key, archetype_name, "
        "colors, label, method, confidence, cards_seen, conditions_met, conditions_unknown, "
        "evidence_json, classified_at) VALUES (?, ?, ?, ?, NULL, ?, 'archetype', "
        "'high', 5, 3, 0, NULL, 't')",
        (match_id, fmt, archetype_key, label, label),
    )


def _insert_manual_override(conn, match_id, label, archetype_key=None):
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, updated_at, archetype_key) "
        "VALUES (?, ?, 't', ?)",
        (match_id, label, archetype_key),
    )


def test_by_opponent_merges_automatic_and_manual_labels_under_one_archetype_key(conn):
    """``v_match_opponent``'s own ``opponent_key`` COALESCE (its latest
    redefinition, ``migrations/035_mtgo_source.sql``) puts
    ``'archetype:' || o.archetype_key`` ahead of
    ``'archetype:' || a.archetype_key``: a manual override that names the
    same ``archetype_key`` as an automatic classification produces the
    identical ``opponent_key`` string, so ``_build_by_opponent``'s dict keyed
    on ``opponent_key`` merges them into one line -- exactly what its own
    docstring claims. A manual override with no ``archetype_key`` at all
    produces ``'manual:' || label`` instead, which the ``LIKE
    'archetype:%'`` filter in ``_build_by_opponent``'s own query excludes,
    landing it in the unclassified gap line."""
    # Two automatically-classified matches, plus one manual override naming
    # the *same* archetype_key but a different free-text label --
    # opponent_label always reads o.label once an override exists
    # (v_match_opponent's own COALESCE puts it first), so this line's label
    # is genuinely a vote between the classifier's wording and the user's.
    _insert_match(conn, "auto1", "win")
    _insert_match(conn, "auto2", "loss")
    _insert_match(conn, "manual_named", "win")
    _insert_auto_classification(conn, "auto1", "boros-aggro", "Boros Aggro")
    _insert_auto_classification(conn, "auto2", "boros-aggro", "Boros Aggro")
    _insert_manual_override(conn, "manual_named", "Boros Beatdown", archetype_key="boros-aggro")

    # A manual override naming no archetype at all -- opponent_key becomes
    # 'manual:Rogue', excluded by the 'archetype:%' filter and counted only
    # in the unclassified gap, never given its own line.
    _insert_match(conn, "manual_unnamed", "loss")
    _insert_manual_override(conn, "manual_unnamed", "Rogue")

    # Filler with no opponent classification at all, only to clear
    # MIN_SAMPLE -- these resolve to opponent_key='unknown' in
    # v_match_opponent, excluded by the same filter and landing in the same
    # gap as manual_unnamed above.
    for i in range(6):
        _insert_match(conn, f"filler{i}", "win" if i % 2 == 0 else "loss")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10  # 3 named + 1 manual_unnamed + 6 filler

    # auto1 + auto2 + manual_named all resolve to opponent_key
    # 'archetype:boros-aggro' and so merge into one MatchupLine: n=3,
    # wins=2 (auto1 win, auto2 loss, manual_named win).
    lines = [line for line in evidence.by_opponent if line.rate.n == 3]
    assert len(lines) == 1
    assert (lines[0].rate.wins, lines[0].rate.n) == (2, 3)
    # label_votes counts 2 "Boros Aggro" (the automatic rows' own a.label)
    # against 1 "Boros Beatdown" (the override's own o.label) -- a plain 2-1
    # majority picks "Boros Aggro" regardless of row order or the
    # alphabetic tie-break, since it isn't a tie.
    assert lines[0].archetype == "Boros Aggro"
    # variants: every distinct label this key has carried, count desc then
    # name -- "Boros Aggro" x2 (auto1, auto2) ahead of "Boros Beatdown" x1
    # (manual_named), regardless of row order or the alphabetic tie-break
    # used for `archetype` above, since this isn't a tie.
    assert lines[0].variants == (("Boros Aggro", 2), ("Boros Beatdown", 1))

    # manual_unnamed (1) + 6 filler matches = 7 unclassified.
    assert any(g.startswith("7 match(es) in the format window") for g in evidence.gaps)


def test_by_opponent_tie_breaks_alphabetically_not_by_row_order(conn):
    """A 1-1 label tie -- one automatic classification, one manual override
    naming the same archetype_key with different wording -- must resolve
    the same way regardless of row order, since the query behind this has
    no ORDER BY and SQLite does not guarantee one. ``manual_tie`` is
    inserted first, so an insertion-order tie-break (e.g. relying on
    ``Counter.most_common``'s own behaviour on equal counts, which keeps
    first-seen order) would see "Boros Beatdown" counted before "Boros
    Aggro" and wrongly pick it; this test would have caught that bug. The
    correct, order-independent answer is alphabetical: "Boros Aggro" sorts
    before "Boros Beatdown"."""
    _insert_match(conn, "manual_tie", "win")
    _insert_manual_override(conn, "manual_tie", "Boros Beatdown", archetype_key="boros-tie")
    _insert_match(conn, "auto_tie", "loss")
    _insert_auto_classification(conn, "auto_tie", "boros-tie", "Boros Aggro")

    for i in range(8):
        _insert_match(conn, f"filler{i}", "win" if i % 2 == 0 else "loss")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    lines = [line for line in evidence.by_opponent if line.rate.n == 2]
    assert len(lines) == 1
    assert lines[0].archetype == "Boros Aggro"
    # Both variants tied at 1 each -- alphabetical, same as the vote above.
    assert lines[0].variants == (("Boros Aggro", 1), ("Boros Beatdown", 1))


def test_by_opponent_overflow_beyond_top_12_is_a_gap(conn):
    """13 distinct classified archetypes, one match each -- only the top 12
    may appear as MatchupLines, and the 13th must be named in a gap line
    instead of silently vanishing, mirroring by_deck's own overflow rule."""
    for i in range(13):
        match_id = f"m{i}"
        _insert_match(conn, match_id, "win")
        _insert_auto_classification(conn, match_id, f"archetype-{i:02d}", f"Archetype {i:02d}")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 13
    assert len(evidence.by_opponent) == 12
    assert any("1 opponent archetype(s) beyond the top 12" in g for g in evidence.gaps)


def test_by_opponent_respects_the_format_window_boundary(conn):
    """One match the instant before window_start, one exactly on it: the
    reset detected here has date=2026-06-01, so window_start=2026-06-02
    (guide/window.py::window_start's own +1-day rule) -- the match dated
    2026-06-01T23:59:59 is out, the one dated 2026-06-02T00:00:00 is in."""
    _insert_ban(conn)
    _insert_match(conn, "before", "win", started_at="2026-06-01T23:59:59")
    _insert_match(conn, "on", "win", started_at="2026-06-02T00:00:00")
    for i in range(8):
        _insert_match(conn, f"filler{i}", "win" if i % 2 == 0 else "loss",
                       started_at="2026-07-01T00:00:00")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.population == 10
    assert evidence.window_start == "2026-06-02"
    assert evidence.format_population == 9  # "before" excluded, all 9 others in


def test_build_coach_evidence_threads_one_window_into_every_report_and_leak_call(
    conn, monkeypatch,
):
    """build_coach_evidence must compute the format-reset window once and
    pass that exact value as consensus_since to every build_match_report it
    makes for a match of that format, and hand every find_leaks call a
    consensus_window resolver giving that format the same value --
    brief_consensus_window.md's own instruction to "reuse that exact value;
    do not compute a second one." Pinned by recording what a real
    (unmocked) build_match_report and find_leaks call receive, rather than
    by inspecting a result that would look the same whether or not the
    window was actually threaded through."""
    _insert_ban(conn)  # reset date 2026-06-01 -> window_start 2026-06-02
    for i in range(10):
        _insert_match(conn, f"m{i}", "win" if i % 2 == 0 else "loss",
                       started_at="2026-07-01T00:00:00")
    conn.commit()

    seen_report_windows = []
    real_build_match_report = evidence_mod.build_match_report

    def recording_build_match_report(conn, match_id, *, consensus_since=None, **kwargs):
        seen_report_windows.append(consensus_since)
        return real_build_match_report(
            conn, match_id, consensus_since=consensus_since, **kwargs
        )

    seen_leak_windows = []
    real_find_leaks = evidence_mod.find_leaks

    def recording_find_leaks(conn, *, consensus_window, **kwargs):
        seen_leak_windows.append(consensus_window("Standard"))
        return real_find_leaks(conn, consensus_window=consensus_window, **kwargs)

    monkeypatch.setattr(evidence_mod, "build_match_report", recording_build_match_report)
    monkeypatch.setattr(evidence_mod, "find_leaks", recording_find_leaks)

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.window_start == "2026-06-02"
    assert seen_report_windows, "build_match_report was never called"
    assert all(w == "2026-06-02" for w in seen_report_windows)
    assert seen_leak_windows, "find_leaks was never called"
    assert all(w == "2026-06-02" for w in seen_leak_windows)


def test_no_reset_uses_the_whole_population_and_reports_a_gap(conn):
    for i in range(10):
        _insert_match(conn, f"m{i}", "win" if i % 2 == 0 else "loss",
                       started_at=f"2026-0{1 + i % 9}-01T00:00:00")
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert evidence.window_start is None
    assert evidence.format_population == evidence.population == 10
    assert any("format reset" in g.lower() or "legality" in g.lower() for g in evidence.gaps)


# --- privacy -----------------------------------------------------------------


def test_privacy_no_opponent_identifiers_survive_into_the_evidence(conn):
    for i in range(9):
        _insert_match(conn, f"m{i}", "win" if i % 2 == 0 else "loss")
    _insert_match(
        conn, "secret_match", "win",
        opponent_name="Sneaky Steve", opponent_user_id="OPP-SECRET-USERID-999",
    )
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, updated_at, archetype_key) "
        "VALUES ('secret_match', 'Boros Aggro', 't', 'boros-aggro')"
    )
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    dump = repr(evidence)
    assert "Sneaky Steve" not in dump
    assert "OPP-SECRET-USERID-999" not in dump
    assert "secret_match" not in dump
    # The manual override still resolves to an archetype line -- an
    # archetype name is not an opponent identifier, so it is expected here.
    assert any(line.archetype == "Boros Aggro" for line in evidence.by_opponent)


# --- frame.py's new role Evidence --------------------------------------------


def _verdict() -> Verdict:
    return Verdict(key="Aggro", name="Mono Red Aggro", method="archetype", met=3, unknown=0,
                    evidence=(), fit=1.0, margin=float("inf"))


def _snapshot(**overrides) -> MatchSnapshot:
    base = dict(
        match_id="m", deck_id=None, self_seat=1, result="win",
        games=(), self_turns=(), lands_played={}, hand_lands={}, turn1_hand_size={},
        deck_land_ratio=None, opponent_plays=(), self_plays=(), deck_game_length=(), play_draw=(),
        candidates=(), own_cards=(), own_archetype=None,
        opponent_key=None, opponent_label=None, opponent_archetype_key=None,
        opponent_revealed_names=frozenset(), opp_consensus=None,
        damage_events=(), life_events=(), countered=(),
        personal_matchup=None, field_matchup=None,
    )
    base.update(overrides)
    return MatchSnapshot(**base)


def test_role_assignment_finding_carries_a_role_evidence_value():
    """coach/evidence.py's by_role rollup reads the role_assignment
    finding's own structured Evidence rather than parsing its prose title --
    this pins down that frame.py actually exposes one, and that this
    fixture's own numbers land on a specific role rather than merely one of
    the three legal strings."""
    own_cards = (
        OwnCard(grp_id=1, name="Play with Fire", type_line="Instant", count=4,
                tags=frozenset({"spot_removal"})),
        OwnCard(grp_id=2, name="Monastery Swiftspear", type_line="Creature — Human Monk",
                count=4, tags=frozenset()),
        OwnCard(grp_id=3, name="Slickshot Show-Off", type_line="Creature — Human Rogue",
                count=4, tags=frozenset()),
    )
    opp_consensus = ArchetypeConsensus(
        archetype_key="ControlArchetype", deck_count=50,
        cards=(
            ConsensusCard(name="Sunfall", grp_id=None, type_line=None, decks_with_card=8,
                          copies=4.0, share=0.8, tags=frozenset({"sweeper"})),
            ConsensusCard(name="Get Lost", grp_id=None, type_line=None, decks_with_card=7,
                          copies=3.5, share=0.7, tags=frozenset({"spot_removal"})),
            ConsensusCard(name="Consider", grp_id=None, type_line=None, decks_with_card=9,
                          copies=4.0, share=0.9, tags=frozenset({"card_draw"})),
        ),
    )
    snap = _snapshot(
        own_cards=own_cards, own_archetype=_verdict(),
        opponent_archetype_key="ControlArchetype", opponent_label="Azorius Control",
        opp_consensus=opp_consensus,
    )
    result = analyze_frame(snap)
    finding = next(f for f in result.findings if f.code == "role_assignment")
    role_evidence = next(e for e in finding.evidence if e.key == "role")

    # frame.py's own vote rule (analyze_frame, ~lines 174-197), worked by hand
    # against _own_profile/_consensus_profile over exactly the cards above:
    #
    # Own profile (12 total weight: 4+4+4 copies):
    #   creature_rate = 8/12 (Swiftspear + Show-Off are creatures, Play with
    #     Fire is not) = 0.667; removal_rate = 4/12 (Play with Fire tagged
    #     spot_removal) = 0.333; card_advantage_rate = 0/12 (no card_draw or
    #     counterspell tag on any own card) = 0.0.
    #
    # Consensus profile (staples(min_share=0.3) keeps all three cards; weight
    #   = share * copies, total = 3.2 + 2.45 + 3.6 = 9.25):
    #   Sunfall (sweeper, weight 0.8*4.0=3.2): removal; type_line is None, so
    #     not a creature.
    #   Get Lost (spot_removal, weight 0.7*3.5=2.45): removal.
    #   Consider (card_draw, weight 0.9*4.0=3.6): card advantage.
    #   -> creature_rate = 0/9.25 = 0.0; removal_rate = 2.45/9.25 ~= 0.265;
    #      card_advantage_rate = 3.6/9.25 ~= 0.389.
    #
    # Votes: own creature_rate (0.667) > opp's (0.0) -> +1 beatdown.
    #   own removal_rate (0.333) > opp's (0.265) -> +1 control.
    #   own card_advantage_rate (0.0) < opp's (0.389) -> +2 beatdown (the
    #     "almost always control" term is weighted double, and it goes
    #     against us here).
    # Total: beatdown 3, control 1 -> beatdown wins regardless of which way
    # the removal vote itself falls, since creature + card-advantage alone
    # already put beatdown at 3 against control's ceiling of 1.
    assert role_evidence.value == "beatdown"


# --- turning_points ------------------------------------------------------


def _turning_report(
    match_id: str,
    result: str,
    games: list[tuple[int, str]],
    turning: dict[int, tuple[int | None, str]],
) -> MatchReport:
    """``games`` is a list of (game_number, game_result); ``turning`` maps a
    game_number that should carry its own ``turning_point`` finding to
    (self_turn_index, severity). A game_number missing from ``turning`` gets
    no finding at all -- the never_behind / too-few-turns / nothing-to-show
    case, indistinguishable from this rollup's own point of view."""
    game_facts = tuple(
        GameFacts(game_number=gn, on_play=None, result=gr, result_reason=None, turn_count=None,
                  self_mulligans=None, opp_mulligans=None)
        for gn, gr in games
    )
    findings = tuple(
        Finding(code="turning_point", analyzer="trajectory", category=Category.TRAJECTORY,
                severity=Severity(severity), confidence=Confidence.PARTIAL, game_number=gn,
                self_turn_index=self_turn_index, title="irrelevant", detail="irrelevant")
        for gn, (self_turn_index, severity) in turning.items()
    )
    return MatchReport(match_id=match_id, deck_id=None, result=result, games=game_facts,
                        findings=findings)


def test_turning_points_bucket_every_lost_game_by_stage_and_severity(conn, monkeypatch):
    """One lost game per (stage, severity) cell (self_turn_index 2/5/8 cross
    decisive/notice), plus three regression cases that must NOT land in a
    bucket:

    * a match the player *won* overall whose one game also carries its own
      turning_point finding -- game.result='win', so Part 0's per-game (not
      per-match) filter must exclude it even though the finding exists;
    * a match won 2-1 whose *first* game was lost and carries its own
      turning_point finding -- this must still be COUNTED (it is a lost
      game, regardless of the match's overall result) -- the exact case
      the per-game-vs-per-match fix targets;
    * a lost game with no turning_point finding at all, which must be
      counted in the gap rather than guessed into a bucket.
    """
    reports: dict[str, MatchReport] = {}

    cell_plan = [
        ("early_dec", 2, "decisive"), ("early_not", 2, "notice"),
        ("mid_dec", 5, "decisive"), ("mid_not", 5, "notice"),
        ("late_dec", 8, "decisive"), ("late_not", 8, "notice"),
    ]
    for match_id, turn_idx, severity in cell_plan:
        _insert_match(conn, match_id, "loss")
        reports[match_id] = _turning_report(match_id, "loss", [(1, "loss")],
                                             {1: (turn_idx, severity)})

    # Won overall, but game 1 (the only game) was also won -- its
    # turning_point finding must never be counted since the game itself was
    # not a loss.
    _insert_match(conn, "won_with_finding", "win")
    reports["won_with_finding"] = _turning_report(
        "won_with_finding", "win", [(1, "win")], {1: (2, "decisive")}
    )

    # Won 2-1 overall, but game 1 was lost and carries its own turning_point
    # finding -- must be counted (early/notice) despite the match's overall
    # result being a win. This is the per-game regression case.
    _insert_match(
        conn, "won_with_a_lost_game", "win",
        games=[
            {"game_number": 1, "on_play": 1, "result": "loss"},
            {"game_number": 2, "on_play": 0, "result": "win"},
            {"game_number": 3, "on_play": 1, "result": "win"},
        ],
    )
    reports["won_with_a_lost_game"] = _turning_report(
        "won_with_a_lost_game", "win",
        [(1, "loss"), (2, "win"), (3, "win")], {1: (3, "notice")},
    )

    # A lost game with no turning_point finding at all.
    _insert_match(conn, "loss_no_finding", "loss")
    reports["loss_no_finding"] = _turning_report(
        "loss_no_finding", "loss", [(1, "loss")], {}
    )

    # A lost game whose turning_point finding has no own-turn number: its
    # own gap, in no bucket and not in the "no finding" count.
    _insert_match(conn, "loss_unnumbered", "loss")
    reports["loss_unnumbered"] = _turning_report(
        "loss_unnumbered", "loss", [(1, "loss")], {1: (None, "decisive")}
    )

    # Filler, only to clear MIN_SAMPLE.
    _insert_match(conn, "filler", "win")
    reports["filler"] = _turning_report("filler", "win", [(1, "win")], {})

    conn.commit()
    monkeypatch.setattr(
        evidence_mod, "build_match_report", lambda conn, match_id, **kwargs: reports[match_id]
    )

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert any(g.startswith("1 lost game(s) have a turning_point finding on a turn with no "
                            "own-turn number") for g in evidence.gaps)
    assert len(evidence.turning_points) == 6
    by_cell = {(b.stage, b.severity): b.games for b in evidence.turning_points}
    # early/notice gets 2: early_not's own game, plus won_with_a_lost_game's
    # dropped game 1 (self_turn_index=3 -> early, severity=notice).
    assert by_cell == {
        ("early", "decisive"): 1, ("early", "notice"): 2,
        ("mid", "decisive"): 1, ("mid", "notice"): 1,
        ("late", "decisive"): 1, ("late", "notice"): 1,
    }
    assert any("1 lost game(s) have no turning_point finding" in g for g in evidence.gaps)


def test_turning_points_missing_report_only_charges_an_overall_loss(conn, monkeypatch):
    """A match with no buildable report at all is only counted toward the
    gap when the match itself was lost outright -- a missing report for a
    match the player *won* makes no claim about any dropped game, per
    ``_build_turning_points``'s own documented (and deliberately
    conservative) rule."""
    reports: dict[str, MatchReport | None] = {}
    _insert_match(conn, "missing_loss", "loss")
    reports["missing_loss"] = None
    _insert_match(conn, "missing_win", "win")
    reports["missing_win"] = None
    for i in range(8):
        mid = f"filler{i}"
        result = "win" if i % 2 == 0 else "loss"
        _insert_match(conn, mid, result)
        reports[mid] = _turning_report(mid, result, [(1, result)], {})
    conn.commit()

    monkeypatch.setattr(
        evidence_mod, "build_match_report", lambda conn, match_id, **kwargs: reports[match_id]
    )
    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert sum(b.games for b in evidence.turning_points) == 0
    # Only missing_loss (1) plus the 4 filler losses with no finding count;
    # missing_win contributes nothing.
    assert any(g.startswith("5 lost game(s) have no turning_point finding") for g in evidence.gaps)


# --- leaks / deck_leaks ----------------------------------------------------


def _no_turns_match(conn, match_id, result, *, deck_id=None):
    """A match with no ``turns`` rows at all (only ``games.turn_count`` set,
    the same shape an MTGO match has -- ``projector/mtgo/project.py`` never
    writes ``turns``). ``review/leaks.py::mana_flags`` reads ``screwed`` as
    unknown (``None``), never ``False``, for a match with no self-turn rows
    to answer the question from at all -- rule 4: unknown is ``NULL``, not a
    guess. This helper does *not* produce a match flagged ``True``; it is
    the "no evidence" fixture for that path specifically."""
    _insert_match(conn, match_id, result, deck_id=deck_id)
    conn.execute(
        "UPDATE games SET turn_count = 9 WHERE match_id = ? AND game_number = 1", (match_id,)
    )


def _insert_self_turns(conn, match_id, *, self_lands_by_turn):
    """Real ``turns`` rows for ``match_id``'s own seat (1), one per turn
    number in ``self_lands_by_turn`` -- the shape ``mana_flags`` reads to
    answer ``screwed`` with a real ``True``/``False`` rather than ``None``.
    Mirrors ``tests/test_leaks.py``'s own synthetic mana-screw fixture."""
    for turn_number, self_lands in self_lands_by_turn:
        conn.execute(
            "INSERT INTO turns (match_id, game_number, turn_number, active_seat, "
            "self_life, opp_life, self_hand, opp_hand, self_lands, self_permanents, "
            "opp_permanents) VALUES (?, 1, ?, 1, 20, 20, 7, 7, ?, 0, 0)",
            (match_id, turn_number, self_lands),
        )


def test_build_leaks_truncates_to_top_n_with_an_overflow_gap(conn, monkeypatch):
    """More recurring finding codes than TOP_LEAKS can show -- the overflow
    must be named in a gap, never silently dropped, mirroring by_deck's and
    by_opponent's own overflow rule."""
    top_leaks = evidence_mod.TOP_LEAKS
    n_codes = top_leaks + 2
    reports: dict[str, MatchReport] = {}
    match_id_i = 0
    for code_i in range(n_codes):
        code = f"leaky_pattern_{code_i}"
        # MIN_SAMPLE matches with the pattern, all losses; MIN_SAMPLE without,
        # all wins -- every code clears _leak_from_counts' per-side gate with
        # an identical, maximal win-rate gap so every one of them actually
        # ranks as a leak (ranking order among them does not matter here).
        for _ in range(MIN_SAMPLE):
            mid = f"with{match_id_i}"
            match_id_i += 1
            _insert_match(conn, mid, "loss")
            reports[mid] = MatchReport(
                match_id=mid, deck_id=None, result="loss",
                findings=(Finding(code=code, analyzer="x", category=Category.RESOURCES,
                                   severity=Severity.NOTICE, confidence=Confidence.OBSERVED,
                                   title="t", detail="d", pattern=code),),
            )
    for _ in range(MIN_SAMPLE):
        mid = f"without{match_id_i}"
        match_id_i += 1
        _insert_match(conn, mid, "win")
        reports[mid] = MatchReport(match_id=mid, deck_id=None, result="win")
    conn.commit()

    monkeypatch.setattr(
        evidence_mod, "build_match_report", lambda conn, match_id, **kwargs: reports[match_id]
    )
    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert len(evidence.leaks) == top_leaks
    assert any(f"2 recurring pattern(s) beyond the top {top_leaks}" in g for g in evidence.gaps)


def test_deck_leaks_gates_on_deck_leak_min_and_below_threshold_is_a_gap(conn, monkeypatch):
    """A deck with fewer than deck_leak_min population matches can never
    clear the leak finder's per-side MIN_SAMPLE gate (best case: every one
    of its matches on one side) and so must never be scanned for its own
    leak table -- it is named in a gap instead, and does not appear in
    deck_leaks."""
    deck_leak_min = evidence_mod.DECK_LEAK_MIN
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('big', 'Big Deck', 'Standard', '{}', 't', 't')"
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('small', 'Small Deck', 'Standard', '{}', 't', 't')"
    )
    reports: dict[str, MatchReport] = {}
    # "big" clears deck_leak_min with a real, clean leak pattern split evenly.
    for i in range(deck_leak_min):
        mid = f"big{i}"
        result = "loss" if i % 2 == 0 else "win"
        _insert_match(conn, mid, result, deck_id="big")
        findings = ()
        if i % 2 == 0:
            findings = (Finding(code="big_pattern", analyzer="x", category=Category.RESOURCES,
                                 severity=Severity.NOTICE, confidence=Confidence.OBSERVED,
                                 title="t", detail="d", pattern="big_pattern"),)
        reports[mid] = MatchReport(match_id=mid, deck_id="big", result=result, findings=findings)
    # "small" is well below deck_leak_min.
    for i in range(3):
        mid = f"small{i}"
        result = "win" if i == 0 else "loss"
        _insert_match(conn, mid, result, deck_id="small")
        reports[mid] = MatchReport(match_id=mid, deck_id="small", result=result)
    conn.commit()

    monkeypatch.setattr(
        evidence_mod, "build_match_report", lambda conn, match_id, **kwargs: reports[match_id]
    )
    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert any(dl.deck_label == "Big Deck" and dl.leaks[0].code == "big_pattern"
               for dl in evidence.deck_leaks)
    assert not any(dl.deck_label == "Small Deck" for dl in evidence.deck_leaks)
    assert any(f"1 deck(s) below {deck_leak_min} population matches" in g for g in evidence.gaps)


# --- _select_examples (pure, no I/O) ---------------------------------------


def _leak(code, win_rate_with, win_rate_without, match_ids_with, n_with=15, n_without=20):
    return evidence_mod.Leak(
        code=code, category="c", sample_title=code, n_with=n_with,
        win_rate_with=win_rate_with, ci_with=(0.0, 1.0), n_without=n_without,
        win_rate_without=win_rate_without, ci_without=(0.0, 1.0),
        gap=abs(win_rate_with - win_rate_without), match_ids_with=tuple(match_ids_with),
    )


def test_select_examples_skips_a_leak_whose_pattern_goes_with_winning():
    """A leak whose ``with`` side wins *more* than its ``without`` side must
    never be offered as an example of a loss -- only a losing-direction leak
    (with < without) ever supplies one, and this leak is the only candidate,
    so the selection must fall through entirely to the recent-loss
    fallback."""
    winning_leak = _leak("good_pattern", win_rate_with=0.8, win_rate_without=0.4,
                          match_ids_with=["m1", "m2"])
    started_at = {"m1": "2026-01-01", "m2": "2026-01-02", "recent": "2026-01-03"}
    chosen = evidence_mod._select_examples([winning_leak], ("recent",), started_at)
    assert chosen == [("recent", "recent_loss")]


def test_select_examples_orders_most_recent_first_with_match_id_tiebreak():
    losing_leak = _leak("bad_pattern", win_rate_with=0.2, win_rate_without=0.6,
                         match_ids_with=["a", "b", "c", "d"])
    started_at = {"a": "2026-01-01", "b": "2026-01-03", "c": "2026-01-03", "d": "2026-01-02"}
    chosen = evidence_mod._select_examples([losing_leak], ("a", "b", "c", "d"), started_at)
    # Most recent first; "b"/"c" tie on date and break alphabetically ("b"
    # before "c"); capped at MAX_EXAMPLES=3, so "a" (oldest) never appears.
    assert chosen == [("b", "bad_pattern"), ("c", "bad_pattern"), ("d", "bad_pattern")]


def test_select_examples_fills_remainder_from_recent_losses_without_duplicates():
    losing_leak = _leak("bad_pattern", win_rate_with=0.1, win_rate_without=0.9,
                         match_ids_with=["a"])
    started_at = {"a": "2026-01-01", "b": "2026-01-05", "c": "2026-01-04", "d": "2026-01-03"}
    chosen = evidence_mod._select_examples([losing_leak], ("a", "b", "c", "d"), started_at)
    # "a" comes from the leak itself; the other two slots fill from every
    # recent loss, most-recent-first, skipping "a" since it is already
    # chosen.
    assert chosen == [("a", "bad_pattern"), ("b", "recent_loss"), ("c", "recent_loss")]


def test_select_examples_falls_back_to_every_recent_loss_when_no_leak_qualifies():
    started_at = {"a": "2026-01-01", "b": "2026-01-02"}
    chosen = evidence_mod._select_examples([], ("a", "b"), started_at)
    assert chosen == [("b", "recent_loss"), ("a", "recent_loss")]


# --- decklists ---------------------------------------------------------------


def _identity(deck_ids=("d1",), name="My Deck", current_cards=None) -> DeckIdentity:
    return DeckIdentity(
        key=f"deck:{deck_ids[0]}", arena_deck_id=None, name=name, format="Standard",
        deck_ids=deck_ids, matches=0, match_wins=0, match_losses=0, games_won=0, games_lost=0,
        first_played=None, last_played=None, current_cards=current_cards or {},
    )


def test_deck_list_for_counts_a_grp_id_with_no_card_row_as_unnamed_not_a_guess(conn):
    """4 copies of grp_id 10 (named) + 1 copy of grp_id 20 (no ``cards`` row
    at all) in the maindeck, 2 copies of grp_id 30 (named) in the sideboard
    -- the missing card's copy must be counted in ``unnamed``, never
    rendered as a guessed name or a "?" placeholder (rule 4)."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (10, 'Lightning Bolt')")
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (30, 'Forest')")
    identity = _identity(current_cards={
        "maindeck": [10, 10, 10, 10, 20],
        "sideboard": [30, 30],
    })
    deck_list, had_unnamed = evidence_mod._deck_list_for(conn, "My Deck", identity)
    assert had_unnamed is True
    assert deck_list == evidence_mod.DeckList(
        label="My Deck", main=((4, "Lightning Bolt"),), side=((2, "Forest"),), unnamed=1,
    )


def test_build_decklists_orders_by_format_window_count_and_skips_zero(conn):
    """Two kept decks, both with real current_cards; the one with more
    format-window matches sorts first, and a kept deck with zero
    format-window matches (all its population matches predate the reset) is
    omitted entirely rather than shown as this report's "current" list."""
    conn.execute("INSERT INTO cards (grp_id, name) VALUES (1, 'Card One')")
    identity_a = _identity(deck_ids=("dA",), name="Deck A",
                            current_cards={"maindeck": [1], "sideboard": []})
    identity_b = _identity(deck_ids=("dB",), name="Deck B",
                            current_cards={"maindeck": [1, 1], "sideboard": []})
    identity_c = _identity(deck_ids=("dC",), name="Deck C (stale)",
                            current_cards={"maindeck": [1, 1, 1], "sideboard": []})
    pop_a = [evidence_mod._PopMatch(match_id=f"a{i}", deck_id="dA", started_at="t", result="win")
             for i in range(2)]
    pop_b = [evidence_mod._PopMatch(match_id=f"b{i}", deck_id="dB", started_at="t", result="win")
             for i in range(1)]
    pop_c = [evidence_mod._PopMatch(match_id="c0", deck_id="dC", started_at="t", result="win")]
    kept_decks = [("Deck A", identity_a, pop_a), ("Deck B", identity_b, pop_b),
                  ("Deck C (stale)", identity_c, pop_c)]
    # Format window only includes Deck B's and Deck A's matches -- Deck C's
    # one population match predates the reset and never appears here.
    format_rows = pop_a + pop_b

    decklists, gaps = evidence_mod._build_decklists(conn, kept_decks, format_rows)
    assert [d.label for d in decklists] == ["Deck A", "Deck B"]
    assert not gaps  # every grp_id here resolves to a real card name


# --- field -------------------------------------------------------------------


def _insert_field_deck(conn, event_id, deck_ord, archetype_key, archetype_name,
                        event_date="2026-07-01", fmt="Standard"):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, format, tier, standings_rows) VALUES (?, 'p', 'sha', 'src', ?, ?, ?, "
        "'C', 0)",
        (event_id, event_id, event_date, fmt),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "colors, label, method, classified_at) VALUES (?, ?, ?, ?, NULL, ?, 'archetype', 't')",
        (event_id, deck_ord, archetype_key, archetype_name, archetype_name),
    )


def test_build_field_groups_variants_shares_by_true_total_and_windows_by_date(conn):
    """Two archetype keys in-window (one with two name variants: 3 "Rakdos
    Midrange" + 1 "Rakdos Sacrifice" = 4 decks; "Azorius Control" = 2 decks
    -> true total 6), one key entirely before the window (5 "Old Deck"
    decks, must not count toward the total or appear as a line at all), and
    a personal rate joined through the same 'archetype:'+key vocabulary
    by_opponent already resolves opponents into."""
    _insert_field_deck(conn, "in1", 0, "rakdos-midrange", "Rakdos Midrange", "2026-07-05")
    _insert_field_deck(conn, "in1", 1, "rakdos-midrange", "Rakdos Midrange", "2026-07-05")
    _insert_field_deck(conn, "in1", 2, "azorius-control", "Azorius Control", "2026-07-05")
    _insert_field_deck(conn, "in2", 0, "rakdos-midrange", "Rakdos Midrange", "2026-07-10")
    _insert_field_deck(conn, "in2", 1, "rakdos-midrange", "Rakdos Sacrifice", "2026-07-10")
    _insert_field_deck(conn, "in2", 2, "azorius-control", "Azorius Control", "2026-07-10")
    for i in range(5):
        _insert_field_deck(conn, "before", i, "old-deck", "Old Deck", "2026-05-01")
    conn.commit()

    opponent_counts_by_key = {"archetype:rakdos-midrange": (3, 5)}
    lines, gaps = evidence_mod._build_field(
        conn, "2026-06-02", opponent_counts_by_key, "Standard"
    )
    assert gaps == []
    assert [line.archetype for line in lines] == ["Rakdos Midrange", "Azorius Control"]

    rakdos = lines[0]
    assert rakdos.decks == 4
    assert rakdos.variants == (("Rakdos Midrange", 3), ("Rakdos Sacrifice", 1))
    assert rakdos.share == pytest.approx(4 / 6)
    assert (rakdos.your_rate.wins, rakdos.your_rate.n) == (3, 5)

    azorius = lines[1]
    assert azorius.decks == 2
    assert azorius.share == pytest.approx(2 / 6)
    # Never faced this archetype at all -- n=0, not absent.
    assert (azorius.your_rate.wins, azorius.your_rate.n) == (0, 0)


def test_build_field_share_denominator_is_the_true_total_even_when_top_n_truncates(conn):
    """11 distinct archetype keys, all in-window, with distinct deck counts
    20..10 -- TOP_FIELD=10 keeps only the top 10 (20..11), but the smallest
    key's 10 decks must still count toward the true total (165), never the
    truncated top-10 sum (155)."""
    for i, count in enumerate(range(20, 9, -1)):  # 20, 19, ..., 10 (11 keys)
        for deck_ord in range(count):
            _insert_field_deck(conn, "big", deck_ord + i * 100, f"key{i}", f"Archetype {i}",
                                "2026-07-01")
    conn.commit()

    lines, gaps = evidence_mod._build_field(conn, None, {}, "Standard")
    assert gaps == []
    assert len(lines) == evidence_mod.TOP_FIELD == 10
    # The largest key (20 decks, "Archetype 0") must share against the true
    # total of 165, not the truncated top-10 sum of 155.
    top = next(line for line in lines if line.decks == 20)
    assert top.share == pytest.approx(20 / 165)
    assert not any(line.decks == 10 for line in lines)  # the 11th-largest was truncated away


def test_build_field_reports_a_gap_when_no_classified_corpus_exists_in_window(conn):
    lines, gaps = evidence_mod._build_field(conn, None, {}, "Standard")
    assert lines == ()
    assert any("No classified field corpus" in g for g in gaps)


def test_field_counts_and_build_field_agree_per_key(conn):
    """``brief/coverage.py::_field_counts`` and ``coach/evidence.py::
    _build_field`` both now build their per-key rows from
    ``guide/field.py::field_by_key`` -- pinned here by comparing their
    output over the same seeded window. Every label below is unique to one
    key, so the label is a safe join column between the two: one key with
    two name variants (3 "Rakdos Midrange" + 1 "Rakdos Sacrifice" = 4
    decks), a second key ("Azorius Control" = 2 decks) -- true total 6."""
    _insert_field_deck(conn, "in1", 0, "rakdos-midrange", "Rakdos Midrange", "2026-07-05")
    _insert_field_deck(conn, "in1", 1, "rakdos-midrange", "Rakdos Midrange", "2026-07-05")
    _insert_field_deck(conn, "in1", 2, "azorius-control", "Azorius Control", "2026-07-05")
    _insert_field_deck(conn, "in2", 0, "rakdos-midrange", "Rakdos Midrange", "2026-07-10")
    _insert_field_deck(conn, "in2", 1, "rakdos-midrange", "Rakdos Sacrifice", "2026-07-10")
    _insert_field_deck(conn, "in2", 2, "azorius-control", "Azorius Control", "2026-07-10")
    conn.commit()

    field_counts, field_total = _field_counts(conn, "Standard", None)
    lines, gaps = evidence_mod._build_field(conn, None, {}, "Standard")
    assert gaps == []

    by_label_counts = {label: n for label, n in field_counts.values()}
    by_label_lines = {line.archetype: line.decks for line in lines}
    assert by_label_counts == {"Rakdos Midrange": 4, "Azorius Control": 2}
    assert by_label_lines == by_label_counts
    assert field_total == 6


# --- metrics_snapshot / progress_since ---------------------------------------


def test_metrics_snapshot_round_trips_through_json(conn):
    for i in range(10):
        _insert_match(conn, f"m{i}", "win" if i % 2 == 0 else "loss")
    conn.commit()
    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    snap = evidence_mod.metrics_snapshot(evidence)
    round_tripped = json.loads(json.dumps(snap))
    assert round_tripped == snap
    # Version 2: skill sections span every format, and the
    # report's format is recorded.
    assert (snap["version"], snap["fmt"]) == (2, "Standard")


def test_progress_since_reports_no_new_matches_when_none_are_newer_than_as_of(conn):
    for i in range(10):
        _insert_match(conn, f"m{i}", "win", started_at="2026-01-01T00:00:00")
    conn.commit()
    lines = evidence_mod.progress_since(conn, {"as_of": "2026-06-01T00:00:00", "leaks": []})
    assert lines == ["No new matches recorded since the last report."]


def test_progress_since_summarises_new_matches_and_a_recurring_leak_code(conn, monkeypatch):
    """Two new matches after as_of, one of them carrying a previously-known
    leak code's own finding -- the recurring line must count only the new
    matches (never the old population), and a code with no new occurrence
    at all must say so rather than silently omit itself."""
    for i in range(10):
        _insert_match(conn, f"old{i}", "win", started_at="2026-01-01T00:00:00")
    _insert_match(conn, "new_with_pattern", "loss", started_at="2026-08-01T00:00:00")
    _insert_match(conn, "new_without_pattern", "win", started_at="2026-08-02T00:00:00")
    conn.commit()

    reports = {
        "new_with_pattern": MatchReport(
            match_id="new_with_pattern", deck_id=None, result="loss",
            findings=(Finding(code="known_leak", analyzer="x", category=Category.RESOURCES,
                               severity=Severity.NOTICE, confidence=Confidence.OBSERVED,
                               title="t", detail="d", pattern="known_leak"),),
        ),
        "new_without_pattern": MatchReport(
            match_id="new_without_pattern", deck_id=None, result="win",
        ),
    }
    monkeypatch.setattr(
        evidence_mod, "build_match_report",
        lambda conn, match_id, **kwargs: reports[match_id],
    )

    metrics = {"as_of": "2026-06-01T00:00:00",
               "leaks": [{"code": "known_leak", "gap": 0.5, "pattern": "Known leak"},
                         {"code": "never_recurred", "gap": 0.3, "pattern": "Gone"}]}
    lines = evidence_mod.progress_since(conn, metrics)
    expected = (
        "2 new match(es) since the last report: 50% (1/2, 95% CI 9–91%) — "  # noqa: RUF001
        "anecdotal, below the sample floor."
    )
    assert lines[0] == expected
    assert any('"known_leak" recurred in 1 of 2 new match(es)' in line for line in lines)
    assert any('"never_recurred" was not observed in any new match.' in line for line in lines)


def test_progress_since_mana_screwed_with_no_turn_data_reports_unmeasured(conn):
    """A previously-known synthetic mana leak code is checked via
    ``mana_flags`` directly on the new matches, not by re-running
    ``find_leaks`` (whose MIN_SAMPLE gate two new matches could never
    clear). When the only new match has no ``turns`` rows at all (the
    ``_no_turns_match`` fixture -- the same shape an MTGO match has),
    ``screwed`` reads ``None``, not ``False``: rule 4 forbids treating "no
    evidence" as "not screwed", so this must read as unmeasured rather than
    silently folding into a 0-of-1 "was not observed" rate."""
    for i in range(10):
        _insert_match(conn, f"old{i}", "win", started_at="2026-01-01T00:00:00")
    _no_turns_match(conn, "new_unmeasured", "loss")
    conn.execute(
        "UPDATE matches SET started_at = '2026-08-01T00:00:00' WHERE match_id = 'new_unmeasured'"
    )
    conn.commit()

    metrics = {"as_of": "2026-06-01T00:00:00",
               "leaks": [{"code": "mana_screwed", "gap": 0.4, "pattern": "Screwed"}]}
    lines = evidence_mod.progress_since(conn, metrics)
    assert any(
        '"mana_screwed" could not be measured in any new match (no turn data).' in line
        for line in lines
    )


def test_progress_since_mana_screwed_denominator_excludes_unmeasured_matches(conn):
    """The recurrence denominator is the new matches whose ``screwed`` flag
    is actually known, not every new match -- a no-turn-data match (the
    ``_no_turns_match`` fixture) must neither count as evidence nor
    dilute the rate. Population: 1 screwed (turns rows, low lands by turn
    4), 2 clean (turns rows, healthy lands), 2 unmeasured (no turns rows at
    all) -- the correct read is "1 of 3", never "1 of 5"."""
    for i in range(10):
        _insert_match(conn, f"old{i}", "win", started_at="2026-01-01T00:00:00")

    _insert_match(conn, "new_screwed", "loss", started_at="2026-08-01T00:00:00")
    _insert_self_turns(conn, "new_screwed", self_lands_by_turn=[(1, 2), (2, 2), (3, 2), (4, 2)])
    for i in range(2):
        mid = f"new_clean{i}"
        _insert_match(conn, mid, "win", started_at="2026-08-01T00:00:00")
        _insert_self_turns(conn, mid, self_lands_by_turn=[(1, 2), (2, 3), (3, 4), (4, 4)])
    for i in range(2):
        _no_turns_match(conn, f"new_unmeasured{i}", "loss")
        conn.execute(
            f"UPDATE matches SET started_at = '2026-08-01T00:00:00' "
            f"WHERE match_id = 'new_unmeasured{i}'"
        )
    conn.commit()

    metrics = {"as_of": "2026-06-01T00:00:00",
               "leaks": [{"code": "mana_screwed", "gap": 0.4, "pattern": "Screwed"}]}
    lines = evidence_mod.progress_since(conn, metrics)
    assert any('"mana_screwed" recurred in 1 of 3 new match(es)' in line for line in lines)


# --- determinism --------------------------------------------------------------


def test_build_coach_evidence_is_deterministic_over_the_same_database(conn):
    for i in range(15):
        _insert_match(conn, f"m{i}", "win" if i % 3 else "loss",
                       started_at=f"2026-0{1 + i % 9}-0{1 + i % 9}T00:00:00")
    conn.commit()
    first = build_coach_evidence(conn, fmt="Standard")
    second = build_coach_evidence(conn, fmt="Standard")
    assert first is not None
    assert first == second


# --- comprehensive privacy over a fuller fixture -----------------------------


def _forbidden_strings(evidence) -> list[str]:
    """Every opponent identifier a real match row could leak, collected once
    so the comprehensive privacy test can assert none of them appear
    anywhere -- deliberately excludes the one stated exception,
    ``ExampleGame.match_id``, which the test checks separately."""
    return ["RealOpponentHandle", "OPP-REAL-USERID-12345", "secret_deck_guid_9999"]


def test_privacy_comprehensive_no_forbidden_identifier_anywhere_except_example_match_id(conn):
    """A fuller fixture -- population, a named deck, an opponent archetype,
    a leak pattern and a real turns-backed loss so at least one worked
    example is actually chosen -- walked field by field (not just repr, so a
    field this test forgets to name still gets covered) for every one of
    the real identifiers a match row carries. ``ExampleGame.match_id`` is
    the module's own documented exception and is checked separately, by
    value rather than by exclusion from the walk, so the exemption is
    pinned to the exact field rather than silently widened to "any string on
    an ExampleGame"."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('d1', 'My Deck', 'Standard', '{}', 't', 't')"
    )
    for i in range(9):
        _insert_match(conn, f"m{i}", "win" if i % 2 == 0 else "loss", deck_id="d1")
    _insert_match(
        conn, "secret_match", "loss", deck_id="d1",
        opponent_name="RealOpponentHandle", opponent_user_id="OPP-REAL-USERID-12345",
    )
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, updated_at, archetype_key) "
        "VALUES ('secret_match', 'Boros Aggro', 't', 'boros-aggro')"
    )
    # A turns row so this loss can actually be picked as a worked example --
    # _build_examples only ever selects a loss with at least one turns row.
    conn.execute(
        "INSERT INTO turns (match_id, game_number, turn_number, active_seat, self_life, "
        "opp_life) VALUES ('secret_match', 1, 1, 1, 20, 20)"
    )
    conn.commit()

    evidence = build_coach_evidence(conn, fmt="Standard")
    assert evidence is not None
    assert len(evidence.examples) > 0  # otherwise this test would be vacuous

    forbidden = _forbidden_strings(evidence)

    def walk(value, path):
        if isinstance(value, str):
            for bad in forbidden:
                assert bad not in value, f"{bad!r} leaked at {path}: {value!r}"
            assert "/home/" not in value and "\\Users\\" not in value, (
                f"a local path leaked at {path}: {value!r}"
            )
        elif isinstance(value, tuple | list):
            for i, item in enumerate(value):
                walk(item, f"{path}[{i}]")
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(k, f"{path}.<key>")
                walk(v, f"{path}.{k}")
        elif hasattr(value, "__dataclass_fields__"):
            for f in value.__dataclass_fields__:
                if isinstance(value, evidence_mod.ExampleGame) and f == "match_id":
                    continue  # the one documented exception
                walk(getattr(value, f), f"{path}.{f}")

    walk(evidence, "evidence")
    # And the exception itself must actually be exercised: at least one
    # example really does carry "secret_match" as its match_id, proving the
    # walk's skip above is narrowing an exemption that exists, not papering
    # over a field that never gets populated.
    assert any(ex.match_id == "secret_match" for ex in evidence.examples)
