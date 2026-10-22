"""Tests for review/narrative.py: the context it builds from an
already-computed MatchReport plus its MatchSnapshot, and the framing
``full_prompt`` wraps it with.

The module makes no call itself (``sensei_top.llm`` does — see
``tests/test_llm.py`` for the credential-gating and fake-completion coverage
around the actual call), so there is nothing here to fake an SDK response
for.

The context deliberately sends the game's shape.
``test_narrative_prompt_carries_no_local_paths`` pins the one thing that
would still be wrong to leak regardless of how much of the game itself is
sent, and is load-bearing because a configured credential means this text
really can leave the machine.
"""

from __future__ import annotations

from sensei_top.review import narrative
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
from sensei_top.review.snapshot import CardPlay, MatchSnapshot, SelfTurnRow

# --- narrative_available -----------------------------------------------------


# --- build_narrative_context --------------------------------------------------


_DEFAULT_GAME = GameFacts(1, True, "win", None, 6, 0, 0)


def _report(findings=(), gaps=(), games=None) -> MatchReport:
    return MatchReport(
        match_id="m1", deck_id=None, result="win",
        games=games if games is not None else (_DEFAULT_GAME,),
        findings=tuple(findings), gaps=tuple(gaps),
    )


def _snap(**overrides) -> MatchSnapshot:
    base = dict(
        match_id="m1", deck_id=None, self_seat=1, result="win",
        games=(), self_turns=(), lands_played={}, hand_lands={}, turn1_hand_size={},
        deck_land_ratio=None, opponent_plays=(), self_plays=(), deck_game_length=(),
        play_draw=(), candidates=(), own_cards=(), own_archetype=None,
        opponent_key=None, opponent_label=None, opponent_archetype_key=None,
        opponent_revealed_names=frozenset(), opp_consensus=None,
        damage_events=(), life_events=(), countered=(),
        personal_matchup=None, field_matchup=None,
    )
    base.update(overrides)
    return MatchSnapshot(**base)


def test_narrative_context_is_none_for_an_empty_report():
    """A report with nothing to say (no findings, no gaps) has nothing to
    narrate either — the route degrades to 'no_report', not an empty prompt."""
    assert narrative.build_narrative_context(_report(), _snap()) is None


def test_narrative_context_lists_findings_with_their_anchor_and_caveats():
    finding = Finding(
        code="turning_point", analyzer="trajectory", category=Category.TRAJECTORY,
        severity=Severity.DECISIVE, confidence=Confidence.PARTIAL,
        title="The game turned on your turn 4",
        detail="Your position went from +0.36 to -0.36 by your turn 4.",
        game_number=1, turn_number=7, self_turn_index=4,
        evidence=(Evidence("drop", "Size of the swing", 0.72),),
        caveats=("Not a claim about which single play caused the swing.",),
    )
    context = narrative.build_narrative_context(_report(findings=[finding]), _snap())
    assert "Findings:" in context
    assert "The game turned on your turn 4" in context
    assert "(game 1, your turn 4)" in context
    assert "caveat: Not a claim about which single play caused the swing." in context


def test_narrative_context_states_the_gaps_as_gaps_not_as_silence():
    """Rule 4's 'not tracked' discipline: what could not be evaluated must
    be named, not silently omitted, so the model never assumes a gap means
    nothing happened."""
    gap = Gap(analyzer="clock", reason="No damage was observed to either player.", game_number=1)
    context = narrative.build_narrative_context(_report(gaps=[gap]), _snap())
    assert "Not evaluated" in context
    assert "No damage was observed to either player." in context


def test_narrative_context_ends_with_the_not_tracked_block():
    finding = Finding(
        code="conceded", analyzer="baseline", category=Category.BASELINE, severity=Severity.NOTE,
        confidence=Confidence.OBSERVED, title="Game ended in a concede",
        detail="This game ended by concession.", game_number=1,
    )
    context = narrative.build_narrative_context(_report(findings=[finding]), _snap())
    assert context.rstrip().endswith(
        "the exact phase or step, and which specific cards were in the opponent's "
        "hand at any point."
    )
    assert "Not tracked by this reader at all, for any match" in context


def test_narrative_context_includes_field_context_when_given():
    finding = Finding(
        code="conceded", analyzer="baseline", category=Category.BASELINE, severity=Severity.NOTE,
        confidence=Confidence.OBSERVED, title="Game ended in a concede",
        detail="This game ended by concession.", game_number=1,
    )
    field = narrative.FieldContext(archetype_label="Momo", matches=12, winrate=0.583)
    context = narrative.build_narrative_context(_report(findings=[finding]), _snap(), field=field)
    assert "Field context" in context
    assert "Momo has won 58% of its 12 tracked real-tournament matches" in context
    assert "not about this player or match" in context


def test_narrative_context_field_context_names_the_reset_window_when_set():
    """A FieldContext built from post-reset rounds only must say so in the
    prompt (docs/metagame.md's "The format-reset boundary") — otherwise the
    windowed number is indistinguishable from one pooled across a ban."""
    finding = Finding(
        code="conceded", analyzer="baseline", category=Category.BASELINE, severity=Severity.NOTE,
        confidence=Confidence.OBSERVED, title="Game ended in a concede",
        detail="This game ended by concession.", game_number=1,
    )
    field = narrative.FieldContext(
        archetype_label="Momo", matches=12, winrate=0.583, since="2026-08-11"
    )
    context = narrative.build_narrative_context(_report(findings=[finding]), _snap(), field=field)
    assert "since 2026-08-11" in context

    field_unwindowed = narrative.FieldContext(archetype_label="Momo", matches=12, winrate=0.583)
    context_unwindowed = narrative.build_narrative_context(
        _report(findings=[finding]), _snap(), field=field_unwindowed
    )
    assert "since" not in context_unwindowed.split("Field context")[1].split("\n")[0]


def test_narrative_context_omits_field_context_when_none():
    finding = Finding(
        code="conceded", analyzer="baseline", category=Category.BASELINE, severity=Severity.NOTE,
        confidence=Confidence.OBSERVED, title="Game ended in a concede",
        detail="This game ended by concession.", game_number=1,
    )
    context = narrative.build_narrative_context(_report(findings=[finding]), _snap())
    assert "Field context" not in context


def test_narrative_context_stays_none_with_field_context_but_no_findings_or_gaps():
    """Field data augments a narrative; it never becomes the only reason to
    send one — an empty report is still nothing to narrate."""
    field = narrative.FieldContext(archetype_label="Momo", matches=12, winrate=0.5)
    assert narrative.build_narrative_context(_report(), _snap(), field=field) is None


def test_narrative_context_includes_the_turn_by_turn_position_track():
    """The whole point of this rewrite: the game's own shape, not just a
    summary of it, so the model can point at a specific turn."""
    finding = Finding(
        code="conceded", analyzer="baseline", category=Category.BASELINE, severity=Severity.NOTE,
        confidence=Confidence.OBSERVED, title="Game ended in a concede",
        detail="This game ended by concession.", game_number=1,
    )
    snap = _snap(
        self_turns=(
            SelfTurnRow(
                game_number=1, turn_number=2, self_turn_index=1, self_life=20, opp_life=18,
                self_hand=6, opp_hand=7, self_lands=1, opp_lands=1, self_permanents=1,
                opp_permanents=0, self_power=1, opp_power=0, self_library=39,
                self_graveyard=0, self_open_mana=0, prev_self_permanents=None,
            ),
        ),
    )
    context = narrative.build_narrative_context(_report(findings=[finding]), snap)
    assert "Game 1 (win), turn by turn" in context
    assert "life 20-18" in context
    assert "hand 6-7" in context


def test_narrative_turn_line_without_an_own_turn_number_drops_the_parenthesis():
    snap = _snap(
        self_turns=(
            SelfTurnRow(
                game_number=1, turn_number=2, self_turn_index=None, self_life=20, opp_life=18,
                self_hand=6, opp_hand=7, self_lands=1, opp_lands=1, self_permanents=1,
                opp_permanents=0, self_power=1, opp_power=0, self_library=39,
                self_graveyard=0, self_open_mana=0, prev_self_permanents=None,
            ),
        ),
    )
    line = narrative.turn_lines_of(snap, 1)[0]
    assert line.startswith("  turn 2, life 20-18")
    assert "your turn" not in line and "None" not in line


def test_narrative_context_includes_both_sides_play_sequence():
    finding = Finding(
        code="conceded", analyzer="baseline", category=Category.BASELINE, severity=Severity.NOTE,
        confidence=Confidence.OBSERVED, title="Game ended in a concede",
        detail="This game ended by concession.", game_number=1,
    )
    snap = _snap(
        self_plays=(CardPlay(1, 3, 100, "Play with Fire", "Resolve"),),
        opponent_plays=(CardPlay(1, 4, 200, "Consider", "Resolve"),),
    )
    context = narrative.build_narrative_context(_report(findings=[finding]), snap)
    assert "turn 3: you resolved Play with Fire" in context
    assert "turn 4: opponent resolved Consider" in context


def test_narrative_prompt_carries_no_local_paths():
    """Leaking a filesystem path reveals the machine and buys the coaching
    nothing — the one thing still worth checking for now that this prompt
    deliberately carries the game's own shape (AGENTS.md rule 5's rewrite
    retired the raw-board-state premise this test used to check instead)."""
    finding = Finding(
        code="conceded", analyzer="baseline", category=Category.BASELINE, severity=Severity.NOTE,
        confidence=Confidence.OBSERVED, title="Game ended in a concede",
        detail="This game ended by concession.", game_number=1,
    )
    snap = _snap(
        self_turns=(
            SelfTurnRow(1, 2, 1, 20, 18, 6, 7, 1, 1, 1, 0, 1, 0, 39, 0, 0, None),
        ),
        self_plays=(CardPlay(1, 3, 100, "Play with Fire", "Resolve"),),
    )
    context = narrative.build_narrative_context(_report(findings=[finding]), snap)
    lowered = context.lower()
    for leaked in ("/home/", "c:\\users", "/users/", "appdata"):
        assert leaked not in lowered


# --- the prompt handed over, whether copied or sent by POST ------------------


def test_full_prompt_puts_the_framing_above_the_evidence():
    """The framing used to travel as a `system` parameter. It is still part
    of the text either path uses: what the API sends via `llm.write_prose`,
    and what a user without a credential configured copies by hand."""
    text = narrative.full_prompt("EVIDENCE-BODY")
    assert narrative.SYSTEM_PROMPT in text
    assert "EVIDENCE-BODY" in text
    assert text.index(narrative.SYSTEM_PROMPT) < text.index("EVIDENCE-BODY")
