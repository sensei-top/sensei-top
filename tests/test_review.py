"""Tests for review/: the post-game match report engine.

Two rules from docs/testing.md matter more here than anywhere else in the
project. Ground truth is read from the fixture or from a synthetic
snapshot's own inputs, never from running an analyzer and pasting its
output into an assertion (rule 8) — every assertion below traces back to a
number that was put into the input on purpose. And every synthetic
MatchSnapshot below exists to exercise one specific, named trap, not to make
a number come out conveniently.
"""

from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path

import pytest

from sensei_top.archetypes.classify import Candidate, SignatureCard, Verdict
from sensei_top.db import open_database
from sensei_top.metagame.tiers import MIN_LARGE_PAPER_PLAYERS, TIER_WORDS
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.review import build_match_report
from sensei_top.review.analyzers import ANALYZERS, analyze_baseline, analyze_information
from sensei_top.review.analyzers.frame import analyze_frame
from sensei_top.review.consensus import ArchetypeConsensus, ConsensusCard
from sensei_top.review.findings import GameFacts
from sensei_top.review.snapshot import (
    CardPlay,
    CounteredCard,
    DamageRow,
    FieldMatchup,
    MatchSnapshot,
    OwnCard,
    PersonalMatchup,
    SelfTurnRow,
    build_snapshot,
)

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
MATCH_LOSS = "fd5624a4-d970-40eb-80aa-fba9d2ce17b3"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"


@pytest.fixture
def db(tmp_path):
    conn = open_database(tmp_path / "t.db")
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    yield conn
    conn.close()


# --- synthetic snapshot builders ---------------------------------------------
# Every field not explicitly overridden gets a bland, uninteresting default,
# so what each test sets stands out as the thing that matters to it.


def _game(game_number: int, **overrides) -> GameFacts:
    base = dict(
        game_number=game_number, on_play=True, result="win", result_reason=None,
        turn_count=6, self_mulligans=0, opp_mulligans=0,
    )
    base.update(overrides)
    return GameFacts(**base)


def _turn(game_number: int, turn_number: int, self_turn_index: int, **overrides) -> SelfTurnRow:
    base = dict(
        game_number=game_number, turn_number=turn_number, self_turn_index=self_turn_index,
        self_life=20, opp_life=20, self_hand=7, opp_hand=7, self_lands=self_turn_index,
        opp_lands=self_turn_index, self_permanents=self_turn_index, opp_permanents=0,
        self_power=None, opp_power=None,
        self_library=40 - turn_number, self_graveyard=0, self_open_mana=0,
        prev_self_permanents=None,
    )
    base.update(overrides)
    return SelfTurnRow(**base)


def _own_card(name: str, type_line: str, tags, count: int = 4, grp_id: int = 1) -> OwnCard:
    return OwnCard(grp_id=grp_id, name=name, type_line=type_line, count=count, tags=tags)


def _consensus_card(
    name: str, share: float, copies: float, tags, type_line: str | None = None
) -> ConsensusCard:
    return ConsensusCard(
        name=name, grp_id=None, type_line=type_line, decks_with_card=int(share * 10),
        copies=copies, share=share, tags=tags,
    )


def _verdict(key: str = "TestArchetype", name: str = "Test Archetype") -> Verdict:
    return Verdict(key=key, name=name, method="archetype", met=3, unknown=0,
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


_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[float]:
    return {float(n) for n in _NUMBER_RE.findall(text)}


def _assert_findings_cite_only_traceable_numbers(findings) -> None:
    for f in findings:
        allowed = {
            float(v) for v in (f.game_number, f.turn_number, f.self_turn_index) if v is not None
        }
        for e in f.evidence:
            if isinstance(e.value, bool):
                continue
            if isinstance(e.value, int | float):
                allowed.add(float(e.value))
        stray = (_numbers_in(f.title) | _numbers_in(f.detail)) - allowed
        assert not stray, (
            f"{f.code} cites {stray} with no backing evidence — "
            f"title={f.title!r} detail={f.detail!r} evidence={f.evidence!r}"
        )


# --- a full role-assignment scenario, reused by several tests ----------------

_OWN_CARDS = (
    _own_card("Play with Fire", "Instant", frozenset({"spot_removal"}), count=4, grp_id=1),
    _own_card("Monastery Swiftspear", "Creature — Human Monk", frozenset(), count=4, grp_id=2),
    _own_card("Slickshot Show-Off", "Creature — Human Rogue", frozenset(), count=4, grp_id=3),
)

_OPP_CONSENSUS = ArchetypeConsensus(
    archetype_key="ControlArchetype",
    deck_count=50,
    cards=(
        _consensus_card("Sunfall", 0.8, 4.0, frozenset({"sweeper"})),
        _consensus_card("Get Lost", 0.7, 3.5, frozenset({"spot_removal"})),
        _consensus_card("Consider", 0.9, 4.0, frozenset({"card_draw"})),
        _consensus_card("Never Shown Card", 0.6, 4.0, frozenset()),
    ),
)


def _role_snapshot(**overrides) -> MatchSnapshot:
    base = dict(
        own_cards=_OWN_CARDS, own_archetype=_verdict("Aggro", "Mono Red Aggro"),
        opponent_archetype_key="ControlArchetype", opponent_label="Azorius Control",
        opp_consensus=_OPP_CONSENSUS,
    )
    base.update(overrides)
    return _snapshot(**base)


# --- turns that were never recorded ------------------------------------------


def test_analyzers_never_assume_a_turn_that_was_not_recorded(db):
    """fa7a4d16 game 2 has turn_count == 24 but only turns 1, 2, 3 and 24 were
    ever captured — the fixture is a curated subset, and an earlier
    investigation in this project got exactly this backwards by treating
    turn 24 as a stray artifact instead of the real final state
    (docs/testing.md). An analyzer written as `for n in range(1, turn_count
    + 1)` would invent findings out of turns that never existed. This is the
    test that would catch it.
    """
    recorded = {
        (row["match_id"], row["game_number"]): {
            r["turn_number"]
            for r in db.execute(
                "SELECT turn_number FROM turns WHERE match_id = ? AND game_number = ?",
                (row["match_id"], row["game_number"]),
            )
        }
        for row in db.execute("SELECT DISTINCT match_id, game_number FROM turns")
    }

    for match_id in (MATCH_LOSS, MATCH_WIN):
        for f in build_match_report(db, match_id).findings:
            if f.turn_number is None:
                continue
            key = (match_id, f.game_number)
            assert f.turn_number in recorded[key], (
                f"{f.code} anchors at turn {f.turn_number} in game {f.game_number}, which "
                f"was never recorded ({sorted(recorded[key])} were)"
            )

    game2_findings = [
        f for f in build_match_report(db, MATCH_WIN).findings
        if f.game_number == 2 and f.turn_number is not None
    ]
    assert all(f.turn_number in (2, 24) for f in game2_findings)


# --- no invented numbers -----------------------------------------------------


def test_no_finding_cites_a_number_it_cannot_show(db):
    """Every number in a finding's title or detail must be traceable to one
    of its own Evidence entries or to its game/turn anchor — otherwise it is,
    by construction, a number the analyzer invented rather than observed."""
    findings = list(build_match_report(db, MATCH_LOSS).findings)
    findings += list(build_match_report(db, MATCH_WIN).findings)

    snap = _role_snapshot(
        games=(
            _game(1, result="loss", turn_count=30, on_play=False, self_mulligans=1,
                  result_reason="ResultReason_Concede"),
            _game(2, result_reason="ResultReason_Timeout"),
        ),
        self_turns=(
            _turn(1, 2, 1, self_power=6, opp_power=0, self_hand=7, opp_hand=3,
                  self_permanents=5),
            _turn(1, 4, 2, self_power=2, opp_power=8, self_hand=2, opp_hand=6,
                  self_permanents=1, prev_self_permanents=3),
            _turn(1, 6, 3, self_life=4, opp_life=20, self_power=0, opp_power=10,
                  self_hand=0, opp_hand=6),
            _turn(1, 8, 4, self_power=9, opp_power=1, self_hand=0, opp_hand=6,
                  self_permanents=5),
        ),
        opponent_plays=(CardPlay(1, 5, 555, "Consider", "Resolve"),),
        opponent_revealed_names=frozenset({"Consider"}),
        deck_game_length=((10, 10, 4), (36, 2, 1)),
        play_draw=((True, 12, 6), (False, 11, 5)),
        damage_events=(
            DamageRow(1, 2, 6, 1, 10, 1, True, None, False),
            DamageRow(1, 4, 3, 1, 20, 2, False, None, True),
        ),
        countered=(CounteredCard(1, 3, True, "Play with Fire"),
                   CounteredCard(1, 3, False, "Consider")),
        personal_matchup=PersonalMatchup(matches_completed=4, matches_won=1,
                                          games_won=3, games_lost=6),
        field_matchup=FieldMatchup(n=25, matches_won=10, matches_lost=15, tier="A"),
        candidates=(
            Candidate(
                key="c1", label="Mono Red", kind="archetype", confidence="high",
                evidence=("Bolt",),
                signature_cards=(SignatureCard("Shock", False), SignatureCard("Bolt", True)),
                fit=0.8, reasons=("matched Bolt",), picked=True,
            ),
        ),
    )
    for analyze in ANALYZERS:
        findings += list(analyze(snap).findings)

    codes = {f.code for f in findings}
    assert {
        "role_assignment", "mulligan_taken", "on_play_context", "race_ahead",
        "turning_point", "beatdown_held_back", "still_live_staples",
        "over_committed_into_sweeper", "card_advantage_swing", "counters_traded",
        "personal_matchup_record", "field_matchup_rate", "long_game", "short_game",
        "lost_on_time", "conceded", "play_draw_split",
    } <= codes, f"scenario did not reach every code under audit: missing {codes}"

    _assert_findings_cite_only_traceable_numbers(findings)


def test_field_matchup_rate_backs_the_tier_floor_number_with_evidence():
    """TIER_WORDS for tiers A and D names the 64-player paper-tournament
    floor in prose; the finding must carry that number as Evidence too, or
    the stray-number audit above would flag it as invented. Tiers B and C
    never mention a floor, so they must not carry the evidence either."""
    snap_d = _snapshot(
        games=(_game(1),), own_archetype=_verdict(),
        field_matchup=FieldMatchup(n=25, matches_won=10, matches_lost=15, tier="D"),
    )
    result_d = analyze_baseline(snap_d)
    finding_d = next(f for f in result_d.findings if f.code == "field_matchup_rate")
    floor_evidence = [e for e in finding_d.evidence if e.key == "paper_size_floor"]
    assert floor_evidence and floor_evidence[0].value == MIN_LARGE_PAPER_PLAYERS
    assert f"Across 25 matches in {TIER_WORDS['D']}" in finding_d.detail
    _assert_findings_cite_only_traceable_numbers([finding_d])

    snap_b = _snapshot(
        games=(_game(1),), own_archetype=_verdict(),
        field_matchup=FieldMatchup(n=25, matches_won=10, matches_lost=15, tier="B"),
    )
    result_b = analyze_baseline(snap_b)
    finding_b = next(f for f in result_b.findings if f.code == "field_matchup_rate")
    assert not [e for e in finding_b.evidence if e.key == "paper_size_floor"]


# --- "your turn N" means self_turn_index, never the shared counter ----------


def test_turning_point_labels_self_turn_index_not_the_shared_turn_counter(db):
    """trajectory.py's turning_point finding used to print
    ``point.turn_number`` — Arena's *shared* counter, which counts both
    players' turns — as "your turn N". On the play that counter runs ahead
    of the player's own turn count, so "your turn 7" could really be their
    4th turn. It must instead read ``self_turn_index`` off the matching
    ``v_self_turns`` row (turn_number is still kept as the finding's own
    anchor, unchanged)."""
    checked = 0
    for match_id in (MATCH_LOSS, MATCH_WIN):
        for f in build_match_report(db, match_id).findings:
            if f.code != "turning_point":
                continue
            expected = db.execute(
                "SELECT self_turn_index FROM v_self_turns "
                "WHERE match_id = ? AND game_number = ? AND turn_number = ?",
                (match_id, f.game_number, f.turn_number),
            ).fetchone()["self_turn_index"]
            assert f.self_turn_index == expected
            assert f"your turn {f.self_turn_index}" in f.title
            checked += 1
    assert checked > 0, "fixture produced no turning_point finding to check"


# --- gaps when cards is empty -------------------------------------------------


def test_frame_reports_a_gap_when_the_own_deck_never_classifies(db):
    """match_session.log never populates `cards` (test_api.py's
    test_card_names_are_null_until_the_card_table_is_populated establishes
    this for the same fixture), so the own deck's card names are all NULL and
    it can never resolve to an archetype — frame must say so, never guess a
    role from an unnamed deck."""
    report = build_match_report(db, MATCH_LOSS)
    frame_gaps = [g for g in report.gaps if g.analyzer == "frame"]
    assert any("did not resolve" in g.reason for g in frame_gaps)
    assert not [f for f in report.findings if f.code == "role_assignment"]


def test_information_reports_a_gap_without_an_opponent_consensus(db):
    report = build_match_report(db, MATCH_LOSS)
    info_gaps = [g for g in report.gaps if g.analyzer == "information"]
    assert info_gaps
    assert not [f for f in report.findings if f.code in
                ("still_live_staples", "over_committed_into_sweeper")]


# --- role assignment ----------------------------------------------------------


def test_role_assignment_reads_beatdown_from_more_creatures_less_removal():
    snap = _role_snapshot()
    result = analyze_frame(snap)
    finding = next(f for f in result.findings if f.code == "role_assignment")
    assert "beatdown" in finding.title.lower()


def test_role_assignment_gaps_without_an_opponent_archetype():
    snap = _snapshot(own_cards=_OWN_CARDS, own_archetype=_verdict())
    result = analyze_frame(snap)
    assert not [f for f in result.findings if f.code == "role_assignment"]
    assert any("opponent" in g.reason.lower() for g in result.gaps)


def test_role_assignment_can_read_control_from_a_creature_heavy_field():
    """Regression for the bug where ``ConsensusCard`` carried no ``type_line``,
    so ``_consensus_profile`` hardcoded the opponent's creature_rate to 0.0 —
    "more creatures ⇒ beatdown" could then only ever vote beatdown. Removal
    and card-draw shares are tied exactly between the two sides here, so the
    creature term alone decides the role: a creature-heavy field should read
    as control (the opponent is the beatdown deck). This is impossible to
    get right while the opponent's own creature rate is pinned to zero — the
    old code would vote beatdown from the *player's* single creature alone.
    """
    own_cards = (
        _own_card("Play with Fire", "Instant", frozenset({"spot_removal"}), count=1, grp_id=1),
        _own_card("Consider", "Instant", frozenset({"card_draw"}), count=1, grp_id=2),
        _own_card("Monastery Swiftspear", "Creature — Human Monk", frozenset(), count=1,
                   grp_id=3),
        _own_card("Filler Spell", "Sorcery", frozenset(), count=7, grp_id=4),
    )
    opp_consensus = ArchetypeConsensus(
        archetype_key="CreatureArchetype", deck_count=50,
        cards=(
            _consensus_card("Sweep This", 0.5, 2.0, frozenset({"spot_removal"})),
            _consensus_card("Draw This", 0.5, 2.0, frozenset({"card_draw"})),
            _consensus_card("Big Beast", 1.0, 5.0, frozenset(), type_line="Creature — Beast"),
            _consensus_card("Filler Card", 1.0, 3.0, frozenset()),
        ),
    )
    snap = _snapshot(
        own_cards=own_cards, own_archetype=_verdict("Aggro", "Mono Red Aggro"),
        opponent_archetype_key="CreatureArchetype", opponent_label="Creature Deck",
        opp_consensus=opp_consensus,
    )
    result = analyze_frame(snap)
    finding = next(f for f in result.findings if f.code == "role_assignment")
    assert "control" in finding.title.lower()


def test_frame_gaps_when_the_field_list_carries_no_signal():
    """A consensus that resolves but tags nothing at all (every rate at
    zero) must report a gap, never guess a role from a signal-free field —
    this is what stops an all-zero opponent side from silently voting
    beatdown for any deck that runs a single creature."""
    opp_consensus = ArchetypeConsensus(
        archetype_key="BlankArchetype", deck_count=50,
        cards=(_consensus_card("Nothing Special", 1.0, 6.0, frozenset()),),
    )
    snap = _role_snapshot(opp_consensus=opp_consensus, opponent_archetype_key="BlankArchetype")
    result = analyze_frame(snap)
    assert not [f for f in result.findings if f.code == "role_assignment"]
    assert any("no creature, removal or card-advantage signal" in g.reason
               for g in result.gaps)


# --- information never claims a sweeper was actually cast --------------------


def test_over_commit_finding_never_claims_the_sweeper_was_held(db):
    """This reader cannot see the opponent's hand — 'unaccounted for' must
    never be worded as 'they had it'."""
    snap = _role_snapshot(
        games=(_game(1),),
        self_turns=(_turn(1, 4, 2, self_permanents=5),),
    )
    result = analyze_information(snap)
    over_commit = [f for f in result.findings if f.code == "over_committed_into_sweeper"]
    assert over_commit
    for f in over_commit:
        text = f"{f.title} {f.detail}".lower()
        assert "they had" not in text
        assert "unaccounted" in text or "had not shown" in text


# --- never a verdict on a mulligan -------------------------------------------


def test_the_report_never_judges_a_mulligan(db):
    """Migration 009 dropped the opening-hand reconstruction because Arena
    only emits a kept hand's transfers after the decision is already
    committed — the hands a player shipped are never in the log at all, so
    nothing here may say a mulligan was right or wrong."""
    report_loss = build_match_report(db, MATCH_LOSS)
    report_win = build_match_report(db, MATCH_WIN)
    banned = ("should have mulligan", "wrong to keep", "bad keep", "mistake to keep")
    frame_findings = [
        f for r in (report_loss, report_win) for f in r.findings if f.analyzer == "frame"
    ]
    assert frame_findings
    for f in frame_findings:
        text = f"{f.title} {f.detail} {' '.join(f.caveats)}".lower()
        assert not any(phrase in text for phrase in banned)

    mulligan_findings = [f for f in frame_findings if f.code == "mulligan_taken"]
    assert mulligan_findings
    for f in mulligan_findings:
        assert any("shipped" in c and "not in the log" in c for c in f.caveats)


# --- sample-size discipline ---------------------------------------------------


def test_sample_gated_findings_are_suppressed_below_the_threshold():
    """A play/draw split under a real sample is noise, not a trend — it must
    read as a gap naming the sample size, never as a suppressed-but-silent
    zero. Same discipline governs the personal and field matchup records."""
    too_few = _snapshot(games=(_game(1),), play_draw=((True, 4, 2), (False, 3, 1)))
    result = analyze_baseline(too_few)
    assert not [f for f in result.findings if f.code == "play_draw_split"]
    assert any("too few" in g.reason for g in result.gaps)

    enough = _snapshot(games=(_game(1),), play_draw=((True, 12, 6), (False, 11, 5)))
    result_enough = analyze_baseline(enough)
    assert any(f.code == "play_draw_split" for f in result_enough.findings)

    thin_field = _snapshot(
        games=(_game(1),), own_archetype=_verdict(),
        field_matchup=FieldMatchup(n=5, matches_won=3, matches_lost=2, tier="A"),
    )
    result_thin = analyze_baseline(thin_field)
    assert not [f for f in result_thin.findings if f.code == "field_matchup_rate"]
    assert any("too few" in g.reason for g in result_thin.gaps)
    assert any(
        g.reason.startswith(f"Only 5 matches of this pairing are on record in {TIER_WORDS['A']}")
        for g in result_thin.gaps
    )


# --- determinism ---------------------------------------------------------------


def test_the_report_is_deterministic(db):
    first = build_match_report(db, MATCH_WIN)
    second = build_match_report(db, MATCH_WIN)
    assert dataclasses.asdict(first) == dataclasses.asdict(second)


# --- truncated sessions ---------------------------------------------------------


def test_a_match_with_no_self_seat_reports_a_gap_not_an_empty_report(db):
    db.execute("UPDATE matches SET self_seat = NULL WHERE match_id = ?", (MATCH_WIN,))
    report = build_match_report(db, MATCH_WIN)
    assert report.findings == ()
    assert len(report.gaps) == 1
    assert report.gaps[0].analyzer == "match_report"
    assert "seat" in report.gaps[0].reason


# --- the reader/projector boundary ----------------------------------------------


_PATTERN_LITERAL_RE = re.compile(r'pattern\s*=\s*"([^"]*)"')


def test_every_pattern_label_is_free_of_digits():
    """``Finding.pattern`` (findings.py) is meant to be a fixed, per-code
    label the leak finder titles a rollup with — never a per-match number.
    That was leaks.py's own defect before ``pattern`` existed:
    ``sample_title`` was whichever match happened to be scanned first, so a
    38-match pattern got headlined with one match's own hand size. A digit
    in a ``pattern=`` literal would be that mistake creeping back in."""
    import sensei_top.review.analyzers as analyzers_pkg

    package_dir = Path(analyzers_pkg.__file__).parent
    found_any = False
    for path in package_dir.rglob("*.py"):
        for match in _PATTERN_LITERAL_RE.finditer(path.read_text()):
            found_any = True
            label = match.group(1)
            assert not any(ch.isdigit() for ch in label), (
                f"{path.name}: pattern={label!r} contains a digit"
            )
    assert found_any, "no pattern= literals found in analyzers/ — did they move?"


def test_analyzers_never_read_raw_events():
    """Mechanical guard for AGENTS.md non-negotiable #1: review/ is a pure
    function of already-projected data and must never touch raw_events."""
    import sensei_top.review as review_pkg

    package_dir = Path(review_pkg.__file__).parent
    for path in package_dir.rglob("*.py"):
        assert "raw_events" not in path.read_text(), f"{path} references raw_events"


# --- view_cache: a per-request cache that must not change any result -----------


def test_build_snapshot_is_unchanged_by_a_shared_view_cache(db):
    """build_snapshot's view_cache memoizes the opponent lookup, the
    personal-matchup aggregate, the opponent-cards lookup and the
    field-matchup lookup — every one of them optional and additive. Sharing
    one cache across every match in the fixture must produce byte-identical
    snapshots to the uncached path."""
    match_ids = [row["match_id"] for row in db.execute("SELECT match_id FROM matches")]
    assert match_ids, "fixture produced no matches -- nothing to compare"
    view_cache: dict = {}
    for match_id in match_ids:
        assert build_snapshot(db, match_id) == build_snapshot(
            db, match_id, view_cache=view_cache
        )


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_pm_match(conn, match_id, result, games_won, games_lost, deck_id="deckA"):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', 't', 't', "
        "?, ?, ?, 'r')",
        (match_id, deck_id, result, games_won, games_lost),
    )


def _insert_pm_override(conn, match_id, archetype_key, label="Boros Aggro"):
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, updated_at, archetype_key) "
        "VALUES (?, ?, 't', ?)",
        (match_id, label, archetype_key),
    )


def test_personal_matchup_matches_the_hand_derived_aggregate_with_and_without_a_view_cache(conn):
    """A synthetic personal-matchup population, same deck and same manually-
    overridden opponent archetype throughout, so every one of these matches
    shares one (opponent_key, deck_id) group with the match under test
    ('target'). Includes a draw, a match with no result yet (never resolved
    -- excluded from matches_completed/matches_won, but its games_won/
    games_lost of NULL still folds into the SUM(COALESCE(..., 0)) the SQL
    computed and the view_cache path must replicate exactly) and a match
    with a NULL games_won.

    Hand-derived from the brief's own stated semantics, not from running the
    code (rule 8):
      matches_completed = count of {m1, m2, m3, m5} (m4 excluded: NULL result) = 4
      matches_won        = count of {m1, m5} ('win')                          = 2
      games_won  = 2(m1) + 1(m2) + 1(m3) + 0(m4) + 0(m5)                      = 4
      games_lost = 0(m1) + 2(m2) + 1(m3) + 0(m4) + 1(m5)                      = 4
    """
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckA', 'A', 'Standard', '{}', 't', 't')"
    )
    rows = [
        ("m1", "win", 2, 0),
        ("m2", "loss", 1, 2),
        ("m3", "draw", 1, 1),
        ("m4", None, None, None),
        ("m5", "win", None, 1),
        ("target", "win", 2, 0),
    ]
    for match_id, result, gw, gl in rows:
        _insert_pm_match(conn, match_id, result, gw, gl)
        _insert_pm_override(conn, match_id, "boros-aggro")
    conn.commit()

    expected = PersonalMatchup(matches_completed=4, matches_won=2, games_won=4, games_lost=4)

    snap_uncached = build_snapshot(conn, "target")
    assert snap_uncached is not None
    assert snap_uncached.personal_matchup == expected

    view_cache: dict = {}
    snap_cached = build_snapshot(conn, "target", view_cache=view_cache)
    assert snap_cached is not None
    assert snap_cached.personal_matchup == expected


# --- consensus_since: the opponent consensus must not cross a format reset ---
# Corpus shape mirrors tests/test_consensus.py's own _store_deck and
# tests/test_guide_window.py's own pre/post-reset split (brief_consensus_window.md
# asks these two be reused rather than a third shape invented for this).


def _store_meta_deck(conn, event_id, deck_ord, archetype_key, mainboard, *, event_date):
    conn.execute(
        "INSERT OR IGNORE INTO meta_event (event_id, path, blob_sha, source, name, "
        "event_date, tier) VALUES (?, 'p', 's', 'mtgo', 'e', ?, 'B')",
        (event_id, event_date),
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
        "VALUES (?, ?, ?, '[]')",
        (event_id, deck_ord, json.dumps(mainboard)),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES (?, ?, ?, 'Name', 'Name', 'archetype', 'now')",
        (event_id, deck_ord, archetype_key),
    )


def _build_reset_straddling_corpus(conn):
    """3 pre-reset decks running a card the post-reset decks never play, and
    5 post-reset decks running a different one — same shape as
    tests/test_consensus.py::test_since_excludes_decks_before_the_window,
    with enough post-reset decks alone to clear build_consensus's own
    min_decks=5 default so an unwindowed and a windowed call both return a
    real consensus rather than one of them returning None for an unrelated
    reason."""
    for i in range(3):
        _store_meta_deck(
            conn, f"pre{i}", 0, "boros-aggro", [{"count": 4, "name": "Old Card"}],
            event_date="2026-08-01",
        )
    for i in range(5):
        _store_meta_deck(
            conn, f"post{i}", 0, "boros-aggro", [{"count": 4, "name": "New Card"}],
            event_date="2026-08-15",
        )


def test_consensus_since_excludes_pre_reset_cards_from_the_opponent_consensus(conn):
    """review/snapshot.py:632's bug, pinned: without consensus_since the
    opponent consensus pools every decklist regardless of a reset in
    between and "Old Card" (banned, in this scenario) leaks into the
    consensus a match report would call a "usual staple". With it passed,
    only the post-reset decklists count."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckA', 'A', 'Standard', '{}', 't', 't')"
    )
    _insert_pm_match(conn, "target", "win", 2, 0)
    _insert_pm_override(conn, "target", "boros-aggro")
    _build_reset_straddling_corpus(conn)
    conn.commit()

    snap_unwindowed = build_snapshot(conn, "target")
    assert snap_unwindowed is not None
    assert snap_unwindowed.opp_consensus is not None
    unwindowed_names = {c.name for c in snap_unwindowed.opp_consensus.cards}
    assert "Old Card" in unwindowed_names
    assert "New Card" in unwindowed_names

    snap_windowed = build_snapshot(conn, "target", consensus_since="2026-08-11")
    assert snap_windowed is not None
    assert snap_windowed.opp_consensus is not None
    windowed_names = {c.name for c in snap_windowed.opp_consensus.cards}
    assert windowed_names == {"New Card"}


def test_shared_consensus_cache_does_not_contaminate_across_windows(conn):
    """Two build_snapshot calls sharing one consensus_cache dict, one with
    consensus_since=None and one with a real window, must not hand each
    other the wrong entry — the whole reason the cache key became
    (archetype_key, consensus_since) rather than archetype_key alone."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES ('deckA', 'A', 'Standard', '{}', 't', 't')"
    )
    _insert_pm_match(conn, "target", "win", 2, 0)
    _insert_pm_override(conn, "target", "boros-aggro")
    _build_reset_straddling_corpus(conn)
    conn.commit()

    consensus_cache: dict = {}
    snap_unwindowed = build_snapshot(conn, "target", consensus_cache=consensus_cache)
    snap_windowed = build_snapshot(
        conn, "target", consensus_since="2026-08-11", consensus_cache=consensus_cache
    )
    assert len(consensus_cache) == 2  # both windows kept their own entry

    unwindowed_names = {c.name for c in snap_unwindowed.opp_consensus.cards}
    windowed_names = {c.name for c in snap_windowed.opp_consensus.cards}
    assert unwindowed_names == {"Old Card", "New Card"}
    assert windowed_names == {"New Card"}

    # Repeating either call returns the exact cached object, not a rebuild
    # that happens to agree -- proof the shared dict is actually being read.
    again_unwindowed = build_snapshot(conn, "target", consensus_cache=consensus_cache)
    again_windowed = build_snapshot(
        conn, "target", consensus_since="2026-08-11", consensus_cache=consensus_cache
    )
    assert again_unwindowed.opp_consensus is snap_unwindowed.opp_consensus
    assert again_windowed.opp_consensus is snap_windowed.opp_consensus


# --- field_matchup must not cross a format reset either ----------------------
# v_meta_matchup only gained a date to filter by in 044 (review/snapshot.py's
# own field_matchup query, unwindowed until this phase). The own-archetype
# side needs a real classification (field_matchup requires own_archetype is
# not None), so this builds one full deck/archetype pipeline rather than
# overriding own_archetype directly the way _role_snapshot does for the
# opponent side.


def _teach_own_archetype(conn, *, deck_id="deckA", key="test-own-archetype"):
    """One card, one archetype definition requiring it, one deck playing
    four copies -- just enough for _classify_own_deck's complete=True path
    to name the deck without any ambiguity to resolve."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, mana_cost, oracle_text) "
        "VALUES (9001, 'Test Own Staple', 'Creature', '{1}{R}', 'Text.')"
    )
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
        "fetched_at) VALUES ('Standard', 'archetype', ?, 'Test Own Archetype', 0, ?, 't')",
        (key, json.dumps({
            "Name": "Test Own Archetype",
            "Conditions": [{"Type": "InMainboard", "Cards": ["Test Own Staple"]}],
        })),
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'A', 'Standard', ?, 't', 't')",
        (deck_id, json.dumps({"maindeck": [9001, 9001, 9001, 9001]})),
    )


def _store_meta_round(
    conn, event_id, *, event_date, own_key, opp_key, own_wins, opp_wins, tier="A"
):
    """One event with one round match between own_key and opp_key --
    populates v_meta_matchup's ``archetype_key = own_key, opponent_key =
    opp_key`` side directly (the other side of the symmetric pair is
    unused by these tests)."""
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, tier) "
        "VALUES (?, 'p', 's', 'mtgo', 'e', ?, ?)",
        (event_id, event_date, tier),
    )
    for deck_ord, key in ((0, own_key), (1, opp_key)):
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json) "
            "VALUES (?, ?, '[]', '[]')",
            (event_id, deck_ord),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, label, method, classified_at) "
            "VALUES (?, ?, ?, ?, ?, 'archetype', 'now')",
            (event_id, deck_ord, key, key, key),
        )
    conn.execute(
        "INSERT INTO meta_round_match (event_id, round_name, deck_ord_a, deck_ord_b, "
        "wins_a, wins_b, draws) VALUES (?, 'Round 1', 0, 1, ?, ?, 0)",
        (event_id, own_wins, opp_wins),
    )


def test_field_matchup_counts_only_rounds_on_or_after_consensus_since(conn):
    """One pre-reset round (own archetype loses) and one post-reset round
    (own archetype wins) for the same pairing. Unwindowed, both count;
    windowed to the post-reset date, only the later round's result shows,
    matching docs/metagame.md's "format-reset boundary" rule that already
    governs the opponent's own consensus."""
    _teach_own_archetype(conn)
    _insert_pm_match(conn, "target", "win", 2, 0)
    _insert_pm_override(conn, "target", "boros-aggro")
    _store_meta_round(
        conn, "pre", event_date="2026-07-01",
        own_key="test-own-archetype", opp_key="boros-aggro", own_wins=0, opp_wins=2,
    )
    _store_meta_round(
        conn, "post", event_date="2026-08-15",
        own_key="test-own-archetype", opp_key="boros-aggro", own_wins=2, opp_wins=0,
    )
    conn.commit()

    snap_unwindowed = build_snapshot(conn, "target")
    assert snap_unwindowed is not None
    assert snap_unwindowed.field_matchup == FieldMatchup(
        n=2, matches_won=1, matches_lost=1, tier="A",
    )
    assert snap_unwindowed.field_since is None

    snap_windowed = build_snapshot(conn, "target", consensus_since="2026-08-01")
    assert snap_windowed is not None
    assert snap_windowed.field_matchup == FieldMatchup(n=1, matches_won=1, matches_lost=0, tier="A")
    assert snap_windowed.field_since == "2026-08-01"


def test_field_matchup_is_none_when_every_round_is_pre_window_and_the_baseline_gap_names_it(conn):
    """Windowing past every stored round must gap, not silently show a
    pre-window number -- and the baseline finding must say which window it
    means, per the brief's binding decision that a gapped field record beats
    a pre-ban one shown unlabeled."""
    _teach_own_archetype(conn)
    _insert_pm_match(conn, "target", "win", 2, 0)
    _insert_pm_override(conn, "target", "boros-aggro")
    _store_meta_round(
        conn, "pre", event_date="2026-07-01",
        own_key="test-own-archetype", opp_key="boros-aggro", own_wins=2, opp_wins=0,
    )
    conn.commit()

    snap = build_snapshot(conn, "target", consensus_since="2026-08-11")
    assert snap is not None
    assert snap.field_matchup is None
    assert snap.field_since == "2026-08-11"

    result = analyze_baseline(snap)
    field_gaps = [g for g in result.gaps if "field" in g.reason.lower()]
    assert field_gaps
    assert any("2026-08-11" in g.reason for g in field_gaps)


# --- the own archetype's format follows the confirmed pick (plan 12, D1/D16) --
# Archetype definitions exist for Standard only, so "was the deck classified"
# is the same question as "did the format resolve to Standard".


def _own_archetype_for(conn, match_id):
    snap = build_snapshot(conn, match_id)
    assert snap is not None
    return snap.own_archetype


def _picked_mtgo_match(conn, match_id, *, deck_format, pick_format):
    """An MTGO match: its deck comes from the pick alone (matches.deck_id is
    NULL for MTGO), and decks.format is what the deck store's FormatCode
    pre-filled, not something the user confirmed."""
    _teach_own_archetype(conn)
    conn.execute("UPDATE decks SET format = ? WHERE deck_id = 'deckA'", (deck_format,))
    _insert_pm_match(conn, match_id, "win", 2, 0, deck_id=None)
    conn.execute("UPDATE matches SET source = 'mtgo' WHERE match_id = ?", (match_id,))
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES (?, 'deckA', ?)",
        (match_id, pick_format),
    )
    conn.commit()


def test_own_archetype_reads_an_arena_decks_format_and_ignores_a_stray_pick(conn):
    """Arena names its deck's format itself, so the pick table never applies
    to an Arena match (v_match_deck.format is NULL for one)."""
    _teach_own_archetype(conn)
    _insert_pm_match(conn, "arena-1", "win", 2, 0)
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) "
        "VALUES ('arena-1', 'deckA', 'Modern')"
    )
    conn.commit()
    assert _own_archetype_for(conn, "arena-1") is not None


def test_own_archetype_prefers_the_confirmed_pick_format_over_the_decks_format(conn):
    """The deck's store format says Modern, the user confirmed Standard: the
    pick wins, so the Standard definitions classify the deck."""
    _picked_mtgo_match(conn, "mtgo-1", deck_format="Modern", pick_format="Standard")
    assert _own_archetype_for(conn, "mtgo-1") is not None


def test_own_archetype_does_not_classify_against_a_format_the_pick_rules_out(conn):
    """The reverse: the deck's store format says Standard, the user confirmed
    Modern, for which no definitions exist. The unconfirmed Standard must not
    classify it."""
    _picked_mtgo_match(conn, "mtgo-1", deck_format="Standard", pick_format="Modern")
    assert _own_archetype_for(conn, "mtgo-1") is None


def test_own_archetype_never_reads_an_unconfirmed_store_format_for_an_mtgo_match(conn):
    """A pick that confirms the deck but no format leaves the store's
    FormatCode as an inference only (D1): the verdict stays unknown rather
    than falling back to decks.format."""
    _picked_mtgo_match(conn, "mtgo-1", deck_format="Standard", pick_format=None)
    assert _own_archetype_for(conn, "mtgo-1") is None


def test_deck_land_ratio_counts_an_unresolved_maindeck_copy_as_unnamed(conn):
    """A maindeck whose every listed card is named, but which lost copies
    when an MTGO deck was resolved, is as partial as one with an unnamed
    card: the snapshot's own ``unnamed_count`` guard carries both."""
    for grp_id, name, type_line in ((7001, "Test Plains", "Basic Land — Plains"),
                                    (7002, "Test Bear", "Creature — Bear")):
        conn.execute(
            "INSERT INTO cards (grp_id, name, type_line) VALUES (?, ?, ?)",
            (grp_id, name, type_line),
        )
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json, first_seen, last_seen) "
        "VALUES ('whole', 'W', ?, 't', 't'), ('short', 'S', ?, 't', 't')",
        (
            json.dumps({"maindeck": [7001, 7002], "unresolved": {"maindeck": 0, "sideboard": 0}}),
            json.dumps({"maindeck": [7001, 7002], "unresolved": {"maindeck": 3, "sideboard": 1}}),
        ),
    )
    _insert_pm_match(conn, "whole-1", "win", 2, 0, deck_id="whole")
    _insert_pm_match(conn, "short-1", "win", 2, 0, deck_id="short")
    conn.commit()

    whole = build_snapshot(conn, "whole-1").deck_land_ratio
    short = build_snapshot(conn, "short-1").deck_land_ratio
    assert (whole.maindeck_size, whole.land_count, whole.unnamed_count) == (2, 1, 0)
    assert (short.maindeck_size, short.land_count) == (2, 1)
    assert short.unnamed_count == 3


def test_own_archetype_of_a_deck_with_unresolved_copies_is_not_judged_complete(conn):
    """Two definitions both require the one card the deck plays, under
    different names. On a complete list that is a tie and the top-ranked
    survivor (the lower key) is named; on a partial list the tie fails the
    margin gate (equal fits, ratio 1.0 against MIN_MARGIN 1.5) and nothing is
    named. The same list with copies counted as unresolved must therefore read
    as a partial one."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line, mana_cost, oracle_text) "
        "VALUES (9001, 'Test Own Staple', 'Creature', '{1}{R}', 'Text.')"
    )
    for key, name in (("alpha", "Test Alpha"), ("beta", "Test Beta")):
        conn.execute(
            "INSERT INTO archetypes (format, kind, source, name, include_color, definition, "
            "fetched_at) VALUES ('Standard', 'archetype', ?, ?, 0, ?, 't')",
            (key, name, json.dumps({
                "Name": name,
                "Conditions": [{"Type": "InMainboard", "Cards": ["Test Own Staple"]}],
            })),
        )
    maindeck = [9001, 9001, 9001, 9001]
    for deck_id, extra in (("whole", {"unresolved": {"maindeck": 0, "sideboard": 0}}),
                           ("arena", {}),
                           ("short", {"unresolved": {"maindeck": 2, "sideboard": 0}})):
        conn.execute(
            "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
            "VALUES (?, 'D', 'Standard', ?, 't', 't')",
            (deck_id, json.dumps({"maindeck": maindeck, **extra})),
        )
        _insert_pm_match(conn, f"{deck_id}-1", "win", 2, 0, deck_id=deck_id)
    conn.commit()

    assert _own_archetype_for(conn, "whole-1").name == "Test Alpha"
    assert _own_archetype_for(conn, "arena-1").name == "Test Alpha"
    assert _own_archetype_for(conn, "short-1") is None
