"""Tests for review/summary.py: the match report's own digest.

``build_summary`` is a pure function of an already-built ``MatchReport`` —
most tests here construct one by hand (ground truth is the input a test
wrote itself, never the summary's own output pasted back in, per
docs/testing.md rule 8). The one exception, the number-grounding audit,
needs a real fixture-backed report to exercise every analyzer at once, the
same posture ``test_review.py``'s own traceability test takes.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest

from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.review import GapGroup, build_match_report, build_summary
from sensei_top.review.findings import (
    Category,
    Confidence,
    Evidence,
    Finding,
    GameFacts,
    Gap,
    MatchReport,
    Severity,
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


def _game(game_number: int, **overrides) -> GameFacts:
    base = dict(
        game_number=game_number, on_play=True, result="loss", result_reason=None,
        turn_count=10, self_mulligans=0, opp_mulligans=0,
    )
    base.update(overrides)
    return GameFacts(**base)


def _race_finding(game_number: int, code: str, self_dealt: int, opp_dealt: int, **overrides):
    base = dict(
        code=code, analyzer="clock", category=Category.CLOCK,
        severity=Severity.NOTICE, confidence=Confidence.OBSERVED, game_number=game_number,
        title="irrelevant", detail="irrelevant", pattern="irrelevant",
        evidence=(
            Evidence("self_damage_dealt", "Damage you dealt", self_dealt),
            Evidence("opp_damage_dealt", "Damage taken", opp_dealt),
        ),
    )
    base.update(overrides)
    return Finding(**base)


def _turning_point(game_number: int, turn_number: int, drop: float, **overrides):
    base = dict(
        code="turning_point", analyzer="trajectory", category=Category.TRAJECTORY,
        severity=Severity.DECISIVE if drop >= 0.30 else Severity.NOTICE,
        confidence=Confidence.PARTIAL, game_number=game_number, turn_number=turn_number,
        title="irrelevant", detail="irrelevant",
        evidence=(Evidence("drop", "Size of the swing", drop),),
    )
    base.update(overrides)
    return Finding(**base)


# --- headline -----------------------------------------------------------------


def test_headline_states_the_score_and_opponent():
    report = MatchReport(
        match_id="m", deck_id=None, result="loss",
        games=(_game(1, result="win"), _game(2, result="loss"), _game(3, result="loss")),
        opponent_label="Boros Dragons",
    )
    summary = build_summary(report)
    assert summary.headline == "Lost 1\u20132 to Boros Dragons"


def test_headline_win_and_draw_put_the_viewers_games_first():
    won = MatchReport(
        match_id="m", deck_id=None, result="win",
        games=(_game(1, result="win"), _game(2, result="loss"), _game(3, result="win")),
        opponent_label="Boros Dragons",
    )
    assert build_summary(won).headline == "Won 2\u20131 vs Boros Dragons"
    drawn = MatchReport(
        match_id="m", deck_id=None, result="draw",
        games=(_game(1, result="win"), _game(2, result="loss")),
        opponent_label="Boros Dragons",
    )
    assert build_summary(drawn).headline == "Drew 1\u20131 with Boros Dragons"


def test_headline_names_an_unidentified_opponent_when_no_label_exists():
    report = MatchReport(match_id="m", deck_id=None, result="win",
                          games=(_game(1, result="win"),), opponent_label=None)
    summary = build_summary(report)
    assert "unidentified" in summary.headline.lower()


# --- subhead: the race-vs-result mismatch --------------------------------------


def test_subhead_is_none_when_no_condition_holds():
    report = MatchReport(match_id="m", deck_id=None, result="win",
                          games=(_game(1, result="win"),), opponent_label="Opp")
    assert build_summary(report).subhead is None


def test_race_mismatch_subhead_fires_only_when_the_race_was_led_every_game_and_still_lost():
    """The clearest real "the numbers don't match the story" pattern this
    report can name: leading the damage race in every game and still
    losing some of them. Both counts in the sentence — the total games and
    the number lost — are plain counts of ``report.games``, not values
    pulled from any single finding's own evidence."""
    games = (_game(1, result="win"), _game(2, result="loss"), _game(3, result="loss"))
    findings = (
        _race_finding(1, "race_ahead", 14, 3),
        _race_finding(2, "race_ahead", 19, 11),
        _race_finding(3, "race_ahead", 18, 8),
    )
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=games,
                          findings=findings, opponent_label="Opp")
    subhead = build_summary(report).subhead
    assert subhead is not None
    assert "led the damage race in all 3 games" in subhead
    assert "lost 2 games" in subhead


def _stranded(game_number: int, cards: int, **overrides):
    base = dict(
        code="cards_stranded_in_a_loss", analyzer="resources", category=Category.RESOURCES,
        severity=Severity.NOTICE, confidence=Confidence.PARTIAL, game_number=game_number,
        turn_number=9, title="irrelevant", detail="irrelevant",
        evidence=(Evidence("stranded_cards", "Cards in hand", cards),),
    )
    base.update(overrides)
    return Finding(**base)


def test_race_mismatch_subhead_names_each_lost_games_top_non_race_beat():
    """After the race sentence, one sentence per lost game in game order:
    its top non-race beat's own label and text, or no single cause. The
    won game gets no sentence."""
    games = (_game(1, result="win"), _game(2, result="loss"), _game(3, result="loss"))
    findings = (
        _race_finding(1, "race_ahead", 14, 3),
        _race_finding(3, "race_ahead", 18, 8, severity=Severity.DECISIVE),
        _race_finding(2, "race_ahead", 19, 11, severity=Severity.DECISIVE),
        _stranded(1, 2),
        _stranded(2, 4),
    )
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=games,
                          findings=findings, opponent_label="Opp")
    assert build_summary(report).subhead == (
        "You led the damage race in all 3 games and still lost 2 games. "
        "Game 2, Stranded: 4 cards left in hand. "
        "Game 3: no single cause stood out."
    )


def test_race_mismatch_subhead_takes_the_most_severe_non_race_beat():
    games = (_game(1, result="loss"),)
    findings = (
        _race_finding(1, "race_ahead", 19, 11),
        _stranded(1, 4, severity=Severity.NOTE),
        _turning_point(1, 7, 0.10, severity=Severity.FLAG),
    )
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=games,
                          findings=findings, opponent_label="Opp")
    subhead = build_summary(report).subhead
    assert subhead is not None
    assert subhead.startswith("You led the damage race in all 1 games and still lost 1 game. "
                              "Game 1, Turned: turn 7 \u00b7 ")
    assert subhead.endswith(".")


def test_never_behind_is_not_a_lost_games_cause():
    """never_behind says the position never swung against you, which names
    nothing that decided the loss."""
    games = (_game(1, result="loss"),)
    findings = (
        _race_finding(1, "race_ahead", 19, 11),
        Finding(
            code="never_behind", analyzer="trajectory", category=Category.TRAJECTORY,
            severity=Severity.DECISIVE, confidence=Confidence.PARTIAL, game_number=1,
            title="Never behind", detail="irrelevant",
        ),
    )
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=games,
                          findings=findings, opponent_label="Opp")
    assert build_summary(report).subhead == (
        "You led the damage race in all 1 games and still lost 1 game. "
        "Game 1: no single cause stood out."
    )


def test_race_mismatch_subhead_does_not_fire_when_the_race_was_not_led_every_game():
    games = (_game(1, result="win"), _game(2, result="loss"))
    findings = (_race_finding(1, "race_ahead", 14, 3),)  # game 2 never led the race
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=games,
                          findings=findings, opponent_label="Opp")
    assert build_summary(report).subhead is None


def test_subhead_falls_back_to_a_lone_decisive_findings_own_title():
    """When the race mismatch does not apply, a single decisive finding's
    own already-audited title is promoted verbatim — nothing new is
    invented for the sentence."""
    games = (_game(1, result="loss"),)
    decisive = _turning_point(1, 21, 0.49, title="The game turned on your turn 21")
    other = Finding(
        code="mulligan_taken", analyzer="frame", category=Category.FRAME,
        severity=Severity.NOTE, confidence=Confidence.OBSERVED, game_number=1,
        title="Kept your opening seven", detail="irrelevant",
    )
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=games,
                          findings=(decisive, other), opponent_label="Opp")
    assert build_summary(report).subhead == "The game turned on your turn 21"


# --- per-game beats -------------------------------------------------------------


def test_game_beats_carry_a_meter_for_the_race():
    games = (_game(1, result="win"),)
    findings = (_race_finding(1, "race_ahead", 14, 3),)
    report = MatchReport(match_id="m", deck_id=None, result="win", games=games,
                          findings=findings, opponent_label="Opp")
    line = build_summary(report).games[0]
    assert len(line.beats) == 1
    beat = line.beats[0]
    assert beat.label == "Race"
    assert beat.meter == (14.0, 3.0)
    assert "14" in beat.text and "3" in beat.text


def test_game_beats_are_capped_and_severity_ordered():
    games = (_game(1, result="loss"),)
    findings = (
        _race_finding(1, "race_behind", 3, 14, severity=Severity.NOTICE),
        _turning_point(1, 5, 0.10, severity=Severity.NOTICE),
        Finding(
            code="cards_stranded_in_a_loss", analyzer="resources",
            category=Category.RESOURCES, severity=Severity.DECISIVE,
            confidence=Confidence.PARTIAL, game_number=1, turn_number=10,
            title="Lost holding 6 cards", detail="irrelevant",
            evidence=(Evidence("stranded_cards", "Cards in hand", 6),),
        ),
        Finding(
            code="over_committed_into_sweeper", analyzer="information",
            category=Category.INFORMATION, severity=Severity.NOTICE,
            confidence=Confidence.PARTIAL, game_number=1, turn_number=8,
            title="irrelevant", detail="irrelevant",
            evidence=(Evidence("peak_permanents", "Permanents", 5),),
        ),
    )
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=games,
                          findings=findings, opponent_label="Opp")
    line = build_summary(report).games[0]
    assert len(line.beats) == 3  # capped, one of the four candidates dropped
    assert line.beats[0].code == "cards_stranded_in_a_loss"  # decisive sorts first
    assert line.beats[0].severity == Severity.DECISIVE


def test_game_line_carries_the_bookkeeping_the_old_report_cards_duplicated():
    game = _game(1, result="loss", result_reason="ResultReason_Concede", turn_count=14,
                  on_play=False, self_mulligans=1)
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=(game,),
                          opponent_label="Opp")
    line = build_summary(report).games[0]
    assert line.result_reason_text == "you conceded"  # a loss: the viewer conceded
    assert line.turn_count == 14
    assert line.on_play is False
    assert line.self_mulligans == 1


# One sentence per game-beat label; two codes sharing a label share it.
_DEFINITIONS = {
    "Race": "Damage each player dealt to the other this game, yours first. Combat between "
            "creatures doesn't count.",
    "Turned": "The turn your position (life, cards and board together) fell furthest in one "
              "step, and how big that swing was. If it never fell, this line says so.",
    "Stranded": "Cards still in your hand on the last turn of a game you lost.",
    "Role": "Whether you played the role the matchup gave you: as the beatdown, attacking "
            "while ahead on board; as control, getting ahead on cards.",
    "Risk": "Your board reached four or more permanents while a sweeper the opponent's deck "
            "usually plays was still unseen.",
}


@pytest.mark.parametrize(("reason", "result", "expected"), [
    ("ResultReason_Concede", "loss", "you conceded"),
    ("ResultReason_Concede", "win", "your opponent conceded"),
    ("ResultReason_Concede", None, "conceded"),
    ("ResultReason_Concede", "draw", "conceded"),
    ("ResultReason_Timeout", "loss", "you ran out of time"),
    ("ResultReason_Timeout", "win", "your opponent ran out of time"),
    ("ResultReason_Timeout", None, "ended on the clock"),
    ("ResultReason_Timeout", "draw", "ended on the clock"),
    (None, "loss", None),
    ("ResultReason_Game", "loss", None),
])
def test_reason_text_names_who_from_the_games_result(reason, result, expected):
    """In a 1v1 game whoever conceded or ran out of time lost; with the
    result unknown or a draw the subjectless words stay."""
    game = _game(1, result=result, result_reason=reason)
    report = MatchReport(match_id="m", deck_id=None, result=None, games=(game,),
                          opponent_label="Opp")
    assert build_summary(report).games[0].result_reason_text == expected


def test_codes_sharing_a_label_share_its_definition_and_matchup_beats_have_none():
    games = (_game(1, result="loss"), _game(2, result="win"))
    findings = (
        _race_finding(1, "race_behind", 3, 14),
        _race_finding(2, "race_ahead", 14, 3),
        _turning_point(1, 5, 0.10),
        Finding(
            code="never_behind", analyzer="trajectory", category=Category.TRAJECTORY,
            severity=Severity.NOTE, confidence=Confidence.PARTIAL, game_number=2,
            title="Never behind", detail="irrelevant",
        ),
        Finding(
            code="role_assignment", analyzer="frame", category=Category.FRAME,
            severity=Severity.NOTICE, confidence=Confidence.PARTIAL, game_number=None,
            title="This matchup casts you as the beatdown", detail="irrelevant",
        ),
    )
    report = MatchReport(match_id="m", deck_id=None, result="draw", games=games,
                          findings=findings, opponent_label="Opp")
    summary = build_summary(report)
    by_code = {b.code: b for g in summary.games for b in g.beats}
    assert by_code["race_behind"].definition == by_code["race_ahead"].definition \
        == _DEFINITIONS["Race"]
    assert by_code["turning_point"].definition == by_code["never_behind"].definition \
        == _DEFINITIONS["Turned"]
    assert by_code["turning_point"].turn_number == 5
    assert by_code["never_behind"].turn_number is None
    assert summary.matchup[0].definition is None


def test_a_match_level_role_finding_is_labelled_role_without_the_game_beats_definition():
    """A match-level finding with no curated label falls back to its
    category's name, which for ROLE is the same word as the game beat's
    label; the game beat's sentence does not describe it, so it has none."""
    uncurated = Finding(
        code="some_match_level_role_read", analyzer="role_play", category=Category.ROLE,
        severity=Severity.NOTE, confidence=Confidence.PARTIAL, game_number=None,
        title="irrelevant", detail="irrelevant",
    )
    report = MatchReport(match_id="m", deck_id=None, result="win", games=(_game(1),),
                          findings=(uncurated,), opponent_label="Opp")
    (beat,) = build_summary(report).matchup
    assert beat.label == "Role"
    assert beat.definition is None


def test_fixture_beats_carry_their_findings_turn_and_their_labels_definition(db):
    """Each game beat's turn is its source finding's own, ``None`` where the
    finding has none, and its definition is its label's sentence. Each game
    line's reason names who from that game's own result."""
    reasons = {
        ("ResultReason_Concede", "loss"): "you conceded",
        ("ResultReason_Concede", "win"): "your opponent conceded",
        ("ResultReason_Timeout", "loss"): "you ran out of time",
        ("ResultReason_Timeout", "win"): "your opponent ran out of time",
    }
    seen_turns: set[bool] = set()
    seen_reasons: set[tuple[str, str]] = set()
    for match_id in (MATCH_LOSS, MATCH_WIN):
        report = build_match_report(db, match_id)
        summary = build_summary(report)
        facts = {g.game_number: g for g in report.games}
        for line in summary.games:
            game = facts[line.game_number]
            key = (game.result_reason, game.result)
            assert line.result_reason_text == reasons[key]
            seen_reasons.add(key)
            for beat in line.beats:
                (source,) = [f for f in report.findings
                             if f.code == beat.code and f.game_number == beat.game_number]
                assert beat.turn_number == source.turn_number
                assert beat.definition == _DEFINITIONS[beat.label]
                seen_turns.add(beat.turn_number is None)
    # The fixture exercises a beat with a turn and one without, and a
    # concession on each side plus a timeout.
    assert seen_turns == {True, False}
    assert ("ResultReason_Concede", "loss") in seen_reasons
    assert ("ResultReason_Concede", "win") in seen_reasons
    assert any(reason == "ResultReason_Timeout" for reason, _ in seen_reasons)


# --- matchup beats ---------------------------------------------------------------


def test_matchup_beats_are_the_game_number_none_findings():
    role = Finding(
        code="role_assignment", analyzer="frame", category=Category.FRAME,
        severity=Severity.NOTICE, confidence=Confidence.PARTIAL, game_number=None,
        title="This matchup casts you as the beatdown", detail="irrelevant",
    )
    per_game = Finding(
        code="mulligan_taken", analyzer="frame", category=Category.FRAME,
        severity=Severity.NOTE, confidence=Confidence.OBSERVED, game_number=1,
        title="irrelevant", detail="irrelevant",
    )
    report = MatchReport(match_id="m", deck_id=None, result="win", games=(_game(1),),
                          findings=(role, per_game), opponent_label="Opp")
    summary = build_summary(report)
    assert [b.code for b in summary.matchup] == ["role_assignment"]
    assert summary.matchup[0].label == "Matchup"


# --- gap grouping -----------------------------------------------------------------


def test_gaps_with_a_shared_cause_group_under_one_heading():
    gaps = (
        Gap("frame", "The opponent's deck was not identified...", cause="opponent_unclassified"),
        Gap("information", "The opponent's archetype was not identified...",
            cause="opponent_unclassified"),
        Gap("role_play", "No clear role was assigned...", cause="opponent_unclassified"),
        Gap("baseline", "Only 8 completed games recorded...", cause="small_sample"),
        Gap("baseline", "Only 3 on the play and 5 on the draw...", cause="small_sample"),
    )
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=(), gaps=gaps,
                          opponent_label="Opp")
    groups = build_summary(report).gap_groups
    assert len(groups) == 2  # 5 raw gaps collapse to 2 real causes
    by_cause = {g.cause: g for g in groups}
    assert len(by_cause["The opponent's deck was never identified as a known archetype"]
               .blocked) == 3
    assert len(by_cause["Not enough of your own match history with this deck yet"].blocked) == 2


def test_an_unrecognized_cause_renders_as_its_own_group():
    gap = Gap("some_analyzer", "A gap with no shared cause.", cause=None)
    report = MatchReport(match_id="m", deck_id=None, result="loss", games=(), gaps=(gap,),
                          opponent_label="Opp")
    groups = build_summary(report).gap_groups
    assert groups == (GapGroup(cause="A gap with no shared cause.", blocked=()),)


# --- determinism -------------------------------------------------------------------


def test_summary_is_deterministic(db):
    report = build_match_report(db, MATCH_LOSS)
    first = build_summary(report)
    second = build_summary(report)
    assert dataclasses.asdict(first) == dataclasses.asdict(second)


# --- every number is grounded -------------------------------------------------------

_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[float]:
    return {float(n) for n in _NUMBER_RE.findall(text)}


def test_summary_never_states_a_number_no_finding_or_game_count_carries(db):
    """Every number in the headline, subhead and a beat's own text must
    trace to a plain count of ``report.games`` (by result), or to one of
    the source report's own findings — their evidence values or their
    game/turn anchors. A stray number would be exactly leaks.py's old
    defect (a number invented for the sentence rather than read from the
    data) recurring one layer up, in the summary rather than a finding."""
    for match_id in (MATCH_LOSS, MATCH_WIN):
        report = build_match_report(db, match_id)
        summary = build_summary(report)

        grounded = {float(len(report.games))}
        for r in ("win", "loss", "draw"):
            grounded.add(float(sum(1 for g in report.games if g.result == r)))
        for f in report.findings:
            for v in (f.game_number, f.turn_number, f.self_turn_index):
                if v is not None:
                    grounded.add(float(v))
            for e in f.evidence:
                if isinstance(e.value, bool):
                    continue
                if isinstance(e.value, int | float):
                    grounded.add(float(e.value))

        texts = [summary.headline]
        if summary.subhead:
            texts.append(summary.subhead)
        for beat in (*summary.matchup, *(b for g in summary.games for b in g.beats)):
            texts.append(beat.text)
            if beat.magnitude:
                texts.append(beat.magnitude)

        for text in texts:
            stray = _numbers_in(text) - grounded
            assert not stray, f"{match_id}: {text!r} cites {stray} with nothing grounding it"
