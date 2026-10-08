"""The match report's own digest: a headline, a per-game read, and the
report's gaps collapsed to their real root causes — built entirely from an
already-computed ``MatchReport``, never a second read of the database (see
``review/__init__.py``'s own rule that nothing here touches ``sqlite3``).

This module *selects and phrases* what the analyzers already found; it
measures nothing new. Every number in ``headline``, ``subhead`` and a
``Beat``'s own text traces to a source ``Finding``'s own ``Evidence`` or its
game/turn anchor, or to a plain count of ``MatchReport.games``/``.findings``
— the same discipline ``findings.py``'s own docstring states for a single
finding, extended here to a summary built from many.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sensei_top.review.findings import Finding, GameFacts, Gap, MatchReport, Severity
from sensei_top.review.position import swing_words

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.DECISIVE: 0, Severity.FLAG: 1, Severity.NOTICE: 2, Severity.NOTE: 3,
}

_MAX_BEATS_PER_GAME = 3

# Which per-game finding codes are worth surfacing as a compact "beat", and
# the short left-column label each one gets — deliberately a small, curated
# set (docs/frontend.md's own "digest, not a second copy of every card").
_GAME_BEAT_LABELS: dict[str, str] = {
    "race_ahead": "Race",
    "race_behind": "Race",
    "race_even": "Race",
    "turning_point": "Turned",
    "never_behind": "Turned",
    "cards_stranded_in_a_loss": "Stranded",
    "beatdown_held_back": "Role",
    "control_never_ahead_on_cards": "Role",
    "over_committed_into_sweeper": "Risk",
}

# Match-level (game_number is None) codes worth a curated left-column label;
# anything else in that bucket falls back to its own category name.
_MATCHUP_LABELS: dict[str, str] = {
    "role_assignment": "Matchup",
    "still_live_staples": "Still live",
    "personal_matchup_record": "Your record",
    "field_matchup_rate": "Field record",
    "play_draw_split": "Play/draw",
}

_RESULT_REASON_WORDS: dict[str, str] = {
    "ResultReason_Concede": "conceded",
    "ResultReason_Timeout": "ended on the clock",
}

# A stable slug (Gap.cause) shared by gaps whose real root cause is the same
# absence, even when the analyzers reporting them differ — the heading each
# group renders under. A gap without a recognized cause renders alone,
# exactly as it did before this module existed.
_CAUSE_HEADINGS: dict[str, str] = {
    "opponent_unclassified": "The opponent's deck was never identified as a known archetype",
    "own_unclassified": "Your own deck's cards weren't recognized",
    "small_sample": "Not enough of your own match history with this deck yet",
    "consensus_unavailable": "Too little tournament data for the opponent's archetype",
}


@dataclass(frozen=True, slots=True)
class Beat:
    """One compact line of the digest — a finding's own title, evidence and
    anchor reduced to what a player scanning the match actually needs."""

    code: str
    label: str
    text: str
    magnitude: str | None
    severity: Severity
    game_number: int | None
    meter: tuple[float, float] | None = None  # (self, opp) for a two-sided proportional bar


@dataclass(frozen=True, slots=True)
class GameLine:
    game_number: int
    result: str | None
    result_reason_text: str | None
    turn_count: int | None
    on_play: bool | None
    self_mulligans: int | None
    beats: tuple[Beat, ...]


@dataclass(frozen=True, slots=True)
class GapGroup:
    cause: str
    blocked: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MatchSummary:
    headline: str
    subhead: str | None
    matchup: tuple[Beat, ...]
    games: tuple[GameLine, ...]
    gap_groups: tuple[GapGroup, ...]


def _reason_text(reason: str | None) -> str | None:
    return _RESULT_REASON_WORDS.get(reason) if reason else None


def _evidence(f: Finding, key: str) -> int | float | str | bool | None:
    return next((e.value for e in f.evidence if e.key == key), None)


def _matchup_beat(f: Finding) -> Beat:
    return Beat(
        code=f.code,
        label=_MATCHUP_LABELS.get(f.code, str(f.category).capitalize()),
        text=f.title,
        magnitude=None,
        severity=f.severity,
        game_number=None,
    )


def _game_beat(f: Finding) -> Beat:
    label = _GAME_BEAT_LABELS[f.code]
    meter: tuple[float, float] | None = None
    magnitude: str | None = None
    text = f.title

    if f.code in ("race_ahead", "race_behind", "race_even"):
        self_dealt = _evidence(f, "self_damage_dealt")
        opp_dealt = _evidence(f, "opp_damage_dealt")
        if isinstance(self_dealt, int | float) and isinstance(opp_dealt, int | float):
            text = f"{self_dealt:g} to {opp_dealt:g}"
            meter = (float(self_dealt), float(opp_dealt))
    elif f.code == "turning_point":
        drop = _evidence(f, "drop")
        if isinstance(drop, int | float):
            magnitude = swing_words(drop)
            text = f"turn {f.turn_number} · {magnitude}" if f.turn_number else magnitude
    elif f.code == "cards_stranded_in_a_loss":
        stranded = _evidence(f, "stranded_cards")
        if stranded is not None:
            text = f"{stranded} cards left in hand"
    elif f.code == "beatdown_held_back":
        held = _evidence(f, "turns_held_back")
        if held is not None:
            text = f"held back {held}x"
    elif f.code == "over_committed_into_sweeper":
        peak = _evidence(f, "peak_permanents")
        if peak is not None:
            text = f"{peak} permanents, sweeper unaccounted for"

    return Beat(
        code=f.code, label=label, text=text, magnitude=magnitude,
        severity=f.severity, game_number=f.game_number, meter=meter,
    )


def _game_line(game: GameFacts, findings: list[Finding]) -> GameLine:
    candidates = sorted(
        (f for f in findings if f.code in _GAME_BEAT_LABELS),
        key=lambda f: _SEVERITY_RANK.get(f.severity, 9),
    )
    beats = tuple(_game_beat(f) for f in candidates[:_MAX_BEATS_PER_GAME])
    return GameLine(
        game_number=game.game_number,
        result=game.result,
        result_reason_text=_reason_text(game.result_reason),
        turn_count=game.turn_count,
        on_play=game.on_play,
        self_mulligans=game.self_mulligans,
        beats=beats,
    )


def _headline(report: MatchReport) -> str:
    opponent = report.opponent_label or "an unidentified opponent"
    wins = sum(1 for g in report.games if g.result == "win")
    losses = sum(1 for g in report.games if g.result == "loss")
    if report.result == "win":
        return f"Won {wins}-{losses} vs {opponent}"
    if report.result == "loss":
        return f"Lost {losses}-{wins} to {opponent}"
    if report.result == "draw":
        return f"Drew {wins}-{losses} with {opponent}"
    return f"Match vs {opponent} is not yet complete"


def _race_mismatch_subhead(report: MatchReport) -> str | None:
    """You led the race in every game and still lost some — the single
    clearest "the numbers don't match the story" pattern in real reports
    (docs/review.md's own diagnosis). Every number here is a count of
    ``report.games``/``.findings``, not a value invented for the sentence."""
    total = len(report.games)
    if total == 0:
        return None
    race_ahead_games = {f.game_number for f in report.findings if f.code == "race_ahead"}
    lost_games = {g.game_number for g in report.games if g.result == "loss"}
    if not lost_games or len(race_ahead_games) != total or not (race_ahead_games & lost_games):
        return None
    n_lost = len(lost_games)
    game_word = "game" if n_lost == 1 else "games"
    return (
        f"You led the damage race in all {total} games and still lost "
        f"{n_lost} {game_word}."
    )


def _subhead(report: MatchReport) -> str | None:
    mismatch = _race_mismatch_subhead(report)
    if mismatch is not None:
        return mismatch
    # A single decisive finding reused verbatim — its own title is already
    # covered by the per-finding traceability test, so this fallback invents
    # nothing new; it just promotes what the report already called decisive.
    decisive = [f for f in report.findings if f.severity == Severity.DECISIVE]
    if len(decisive) == 1:
        return decisive[0].title
    return None


def _group_gaps(gaps: tuple[Gap, ...]) -> tuple[GapGroup, ...]:
    grouped: dict[str, list[str]] = defaultdict(list)
    order: list[str] = []
    ungrouped: list[str] = []
    for g in gaps:
        if g.cause is not None and g.cause in _CAUSE_HEADINGS:
            if g.cause not in grouped:
                order.append(g.cause)
            grouped[g.cause].append(g.reason)
        else:
            ungrouped.append(g.reason)
    groups = [GapGroup(cause=_CAUSE_HEADINGS[c], blocked=tuple(grouped[c])) for c in order]
    groups.extend(GapGroup(cause=reason, blocked=()) for reason in ungrouped)
    return tuple(groups)


def build_summary(report: MatchReport) -> MatchSummary:
    findings_by_game: dict[int, list[Finding]] = defaultdict(list)
    matchup_findings: list[Finding] = []
    for f in report.findings:
        if f.game_number is None:
            matchup_findings.append(f)
        else:
            findings_by_game[f.game_number].append(f)

    matchup_findings.sort(key=lambda f: _SEVERITY_RANK.get(f.severity, 9))

    return MatchSummary(
        headline=_headline(report),
        subhead=_subhead(report),
        matchup=tuple(_matchup_beat(f) for f in matchup_findings),
        games=tuple(
            _game_line(game, findings_by_game.get(game.game_number, []))
            for game in report.games
        ),
        gap_groups=_group_gaps(report.gaps),
    )
