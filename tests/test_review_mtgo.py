"""Whether ``build_match_report`` degrades correctly for an MTGO match.

``projector/mtgo/project.py`` writes only ``matches``, ``games`` and
``card_events`` for an MTGO match — never ``turns``, ``turn_zones``,
``combat_*``, ``damage_events``, ``life_events``, ``game_decks``,
``deck_guids``, ``decks`` or ``rank_snapshot``, and ``deck_id`` is always
``NULL`` (``docs/architecture.md``'s MTGO section, ``AGENTS.md``'s repo map).
Every analyzer in ``review/analyzers/`` that reads ``self_turns``, a
deck-scoped view, or ``damage_events`` must therefore report a ``Gap`` for an
MTGO match — never a finding built by silently reading that absence as zero
self-turns, zero damage, or zero deck history (rule 4; ``review/leaks.py``'s
``_mana_flags`` is held to the same rule in ``tests/test_leaks.py``).

The one analyzer with genuine MTGO signal is ``frame.py``'s opening-hand
findings (mulligan count, on/off the play): ``self_mulligans``/``on_play`` are
columns ``project_mtgo()`` writes directly onto ``games``, independent of the
turns table entirely, so those two findings are real here.

The fixture and its ground truth (2 games, Player1 wins 2-0) are the ones
``tests/test_projector_mtgo.py`` derived from ``uv run python
scripts/mtgo_probe.py tests/fixtures/mtgo_match_session.log --force --lines
400`` — see that file's module docstring for the full citation. The two
values the frame test needs come from the same transcript: game 1, Player1
chooses to play first; game 2, Player2000 does; Player1 begins both games with
seven cards (no mulligan).
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.mtgo.project import project_mtgo
from sensei_top.review import build_match_report
from sensei_top.review.snapshot import build_snapshot

FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"
FIXTURE_BYTES = FIXTURE.read_bytes()
GUID = "f2244feb-54e1-48ec-b3c5-711b20844adf"
_SOURCE_FILE = "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat"

# The 7 entries in review/analyzers/ANALYZERS, named by their own ANALYZER
# constant -- every one of them must show up in either report.findings or
# report.gaps for this match, or it silently swallowed the MTGO shape.
_ANALYZER_NAMES = {
    "baseline", "clock", "frame", "information", "resources", "role_play", "trajectory",
}

# Codes that can only ever be produced by treating an empty self_turns read
# (trajectory/resources/role_play) or an empty damage_events/opponent-consensus
# read (information) as real zeros rather than as missing data -- the class of
# bug review/leaks.py's mana flags are held to as well, checked here for every
# analyzer at once.
_TURNS_OR_DAMAGE_DERIVED_CODES = {
    "never_behind", "turning_point",              # trajectory: needs self_turns
    "card_advantage_swing", "cards_stranded_in_a_loss",  # resources: needs self_turns
    "beatdown_held_back", "control_never_ahead_on_cards",  # role_play: needs self_turns
    "over_committed_into_sweeper",                # information: needs self_turns
}


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_mtgo_row(conn, *, data: bytes, logged_at: str, source_file: str = _SOURCE_FILE) -> None:
    payload = base64.b64encode(data).decode("ascii")
    digest = hashlib.sha256(f"{source_file}:{logged_at}:{len(data)}".encode()).hexdigest()
    conn.execute(
        """
        INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source)
             VALUES (?, ?, ?, 'event', 'MtgoGameLog', ?, 'mtgo')
        """,
        (digest, source_file, logged_at, payload),
    )


@pytest.fixture
def db(conn):
    """The real MTGO fixture, ingested and projected -- no ``cards`` rows
    seeded, exactly like ``test_review.py``'s own ``db`` fixture leaves
    ``cards`` empty for the Arena fixture (its
    ``test_frame_reports_a_gap_when_the_own_deck_never_classifies`` says so
    directly). Seeding ``cards`` here would not change any analyzer's
    outcome: every deck-/consensus-scoped path is already gated on
    ``deck_id`` (always ``NULL`` for MTGO) or on a metagame corpus this
    scratch database never has, regardless of whether card names resolve."""
    _insert_mtgo_row(conn, data=FIXTURE_BYTES, logged_at="2026-09-14T12:42:37")
    project_mtgo(conn, "Player1")
    return conn


def test_build_match_report_does_not_crash_on_a_projected_mtgo_match(db):
    report = build_match_report(db, GUID)
    assert report is not None
    assert report.match_id == GUID
    assert report.result == "win"
    assert len(report.games) == 2


def test_every_analyzer_is_represented_by_a_finding_or_a_gap(db):
    report = build_match_report(db, GUID)
    seen = {f.analyzer for f in report.findings} | {g.analyzer for g in report.gaps}
    assert seen == _ANALYZER_NAMES


def test_no_finding_anywhere_rests_on_an_empty_turns_or_damage_read(db):
    """Rule 4, checked against the whole report at once."""
    report = build_match_report(db, GUID)
    assert not ({f.code for f in report.findings} & _TURNS_OR_DAMAGE_DERIVED_CODES)


# --- per-analyzer outcomes ------------------------------------------------


def test_clock_gaps_for_lack_of_damage_events(db):
    """``project_mtgo`` never writes ``damage_events`` -- clock.py must say
    so, not read the empty table as "no race happened, 0-0"."""
    report = build_match_report(db, GUID)
    assert not [f for f in report.findings if f.analyzer == "clock"]
    clock_gaps = [g for g in report.gaps if g.analyzer == "clock"]
    assert any("No damage was observed" in g.reason for g in clock_gaps)


def test_trajectory_gaps_once_per_game_never_reports_never_behind(db):
    """With ``self_turns`` always empty for MTGO, ``_positions`` is always
    empty, and trajectory.py must gap on "too few turns" rather than let
    ``turning_point([])`` return ``None`` and read that as "the position
    never dropped" -- a finding that would rest entirely on data that was
    never recorded, not on data that showed a real, flat trajectory."""
    report = build_match_report(db, GUID)
    assert not [f for f in report.findings if f.analyzer == "trajectory"]
    traj_gaps = [g for g in report.gaps if g.analyzer == "trajectory"]
    assert len(traj_gaps) == 2  # one per game
    assert all("Too few turns" in g.reason for g in traj_gaps)


def test_resources_gaps_once_per_game_for_lack_of_turn_rows(db):
    """No ``self_turns`` rows means hand sizes were never recorded on any
    turn -- resources.py must gap per game, never report a flat (zero)
    card-advantage swing or a "0 cards stranded" finding."""
    report = build_match_report(db, GUID)
    assert not [f for f in report.findings if f.analyzer == "resources"]
    res_gaps = [g for g in report.gaps if g.analyzer == "resources"]
    assert len(res_gaps) == 2
    assert all("Hand sizes for both players were never recorded" in g.reason for g in res_gaps)


def test_role_play_gaps_for_lack_of_own_archetype(db):
    """``deck_id`` is always ``NULL`` for MTGO, so ``own_archetype`` never
    resolves -- role_play.py must gap on that, never assign or check a role
    for an unclassified deck."""
    report = build_match_report(db, GUID)
    assert not [f for f in report.findings if f.analyzer == "role_play"]
    rp_gaps = [g for g in report.gaps if g.analyzer == "role_play"]
    assert len(rp_gaps) == 1


def test_information_gaps_without_an_opponent_consensus(db):
    """No metagame corpus in this scratch database (and no ``cards`` rows to
    resolve an opponent archetype from either) means ``opp_consensus`` is
    always ``None`` -- information.py must gap, never claim every staple
    "showed up" from a consensus it never had."""
    report = build_match_report(db, GUID)
    assert not [f for f in report.findings if f.analyzer == "information"]
    assert [g for g in report.gaps if g.analyzer == "information"]


def test_baseline_gaps_on_every_deck_scoped_comparison(db):
    """``deck_game_length``, ``play_draw``, ``personal_matchup`` and
    ``field_matchup`` are all gated on ``deck_id`` (``v_deck_game_length``,
    ``v_play_draw_winrate``) or on ``own_archetype``/``opponent_archetype_key``
    -- all always ``NULL``/``None`` for MTGO -- so baseline.py must gap on
    all four, never read "0 games recorded" as a real average of zero games."""
    report = build_match_report(db, GUID)
    assert not [f for f in report.findings if f.analyzer == "baseline"]
    base_gaps = [g for g in report.gaps if g.analyzer == "baseline"]
    assert len(base_gaps) == 4


def test_frame_reports_real_opening_hand_findings_from_the_games_table(db):
    """The one analyzer with genuine MTGO signal: ``self_mulligans``/
    ``on_play`` are columns ``project_mtgo()`` writes directly, independent
    of the turns table. Expected values are the transcript's own (module
    docstring): Player1 keeps seven in both games, is on the play in game 1
    and on the draw in game 2."""
    report = build_match_report(db, GUID)
    frame_findings = [f for f in report.findings if f.analyzer == "frame"]
    frame_gaps = [g for g in report.gaps if g.analyzer == "frame"]

    mulligan_findings = {f.game_number: f for f in frame_findings if f.code == "mulligan_taken"}
    play_findings = {f.game_number: f for f in frame_findings if f.code == "on_play_context"}
    assert {n: f.evidence[0].value for n, f in mulligan_findings.items()} == {1: 0, 2: 0}
    assert {n: f.title for n, f in mulligan_findings.items()} == {
        1: "Kept your opening seven", 2: "Kept your opening seven",
    }
    assert {n: f.title for n, f in play_findings.items()} == {
        1: "On the play", 2: "On the draw",
    }

    # own_archetype is always None for MTGO -> role_assignment always gaps,
    # never fires alongside the two real opening-hand findings above.
    assert not [f for f in frame_findings if f.code == "role_assignment"]
    assert any(g.cause == "own_unclassified" for g in frame_gaps)


def _pick_deck(conn, deck_id="mtgo-picked-deck"):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, 'Picked', NULL, '{}', 't', 't')",
        (deck_id,),
    )
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) VALUES (?, ?, 'Modern')",
        (GUID, deck_id),
    )
    conn.commit()
    return deck_id


def test_the_snapshot_reads_the_picked_deck_and_an_unpicked_match_has_none(db):
    assert build_snapshot(db, GUID).deck_id is None
    deck_id = _pick_deck(db)
    assert build_snapshot(db, GUID).deck_id == deck_id


def test_a_picked_deck_does_not_turn_missing_turns_into_findings(db):
    """With a deck the deck-scoped reads run, but ``turns`` is still empty:
    the same rule 4 check as the unpicked report, over the whole report."""
    _pick_deck(db)
    report = build_match_report(db, GUID)
    assert report is not None
    assert not ({f.code for f in report.findings} & _TURNS_OR_DAMAGE_DERIVED_CODES)
