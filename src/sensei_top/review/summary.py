"""The match report's own digest, built entirely from an already-computed
``MatchReport``, never a second read of the database. See docs/review.md,
"The match summary (`review/summary.py`)".

Every number in ``headline``, ``subhead`` and a ``Beat``'s own text traces
to a source ``Finding``'s own ``Evidence`` or its game/turn anchor, or to a
plain count of ``MatchReport.games``/``.findings``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sensei_top.i18n import N_, _, decimal, ngettext
from sensei_top.review.findings import Category, Finding, GameFacts, Gap, MatchReport, Severity
from sensei_top.review.position import swing_words

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.DECISIVE: 0, Severity.FLAG: 1, Severity.NOTICE: 2, Severity.NOTE: 3,
}

_MAX_BEATS_PER_GAME = 3

# Which per-game finding codes are worth surfacing as a compact "beat", and
# the short left-column label each one gets — deliberately a small, curated
# set (docs/review.md, "The match summary (`review/summary.py`)").
_GAME_BEAT_LABELS: dict[str, str] = {
    "race_ahead": N_("Race"),
    "race_behind": N_("Race"),
    "race_even": N_("Race"),
    "turning_point": N_("Turned"),
    "never_behind": N_("Turned"),
    "cards_stranded_in_a_loss": N_("Stranded"),
    "beatdown_held_back": N_("Role"),
    "control_never_ahead_on_cards": N_("Role"),
    "over_committed_into_sweeper": N_("Risk"),
}

# One plain sentence per game-beat label, keyed by the label's msgid, not by
# code: two codes sharing a label share its definition. A label with no entry
# gives its beat ``definition=None``.
_GAME_BEAT_DEFINITIONS: dict[str, str] = {
    "Race": N_("Damage each player dealt to the other this game, yours first. Combat "
               "between creatures doesn't count."),
    "Turned": N_("The turn your position (life, cards and board together) fell furthest in "
                 "one step, and how big that swing was. If it never fell, this line says so."),
    "Stranded": N_("Cards still in your hand on the last turn of a game you lost."),
    "Role": N_("Whether you played the role the matchup gave you: as the beatdown, attacking "
               "while ahead on board; as control, getting ahead on cards."),
    "Risk": N_("Your board reached four or more permanents while a sweeper the opponent's "
               "deck usually plays was still unseen."),
}

_RACE_CODES = frozenset({"race_ahead", "race_behind", "race_even"})

# Beats that never name what decided a lost game: the race (the subhead's own
# premise) and never_behind (the position never swung against you).
_NOT_A_CAUSE = _RACE_CODES | {"never_behind"}

# Match-level (game_number is None) codes worth a curated left-column label;
# anything else in that bucket falls back to its own category name.
_MATCHUP_LABELS: dict[str, str] = {
    "role_assignment": N_("Matchup"),
    "still_live_staples": N_("Still live"),
    "personal_matchup_record": N_("Your record"),
    "field_matchup_rate": N_("Field record"),
    "play_draw_split": N_("Play/draw"),
}

# Keyed by (reason, result): in a 1v1 game whoever conceded or ran out of
# time lost. A result outside "loss"/"win" keeps the subjectless words.
_RESULT_REASON_WORDS: dict[tuple[str, str | None], str] = {
    ("ResultReason_Concede", "loss"): N_("you conceded"),
    ("ResultReason_Concede", "win"): N_("your opponent conceded"),
    ("ResultReason_Concede", None): N_("conceded"),
    ("ResultReason_Timeout", "loss"): N_("you ran out of time"),
    ("ResultReason_Timeout", "win"): N_("your opponent ran out of time"),
    ("ResultReason_Timeout", None): N_("ended on the clock"),
}

# A stable slug (Gap.cause) shared by gaps whose real root cause is the same
# absence, even when the analyzers reporting them differ — the heading each
# group renders under. A gap without a recognized cause renders alone.
_CAUSE_HEADINGS: dict[str, str] = {
    "opponent_unclassified": N_("The opponent's deck was never identified as a known "
                                "archetype"),
    "own_unclassified": N_("Your own deck's cards weren't recognized"),
    "small_sample": N_("Not enough of your own match history with this deck yet"),
    "consensus_unavailable": N_("Too little tournament data for the opponent's archetype"),
}

# The category is an enum value, never display text: the fallback label for a
# match-level finding with no curated one.
_CATEGORY_LABELS: dict[Category, str] = {
    Category.FRAME: N_("Frame"),
    Category.CLOCK: N_("Clock"),
    Category.TRAJECTORY: N_("Trajectory"),
    Category.ROLE: N_("Role"),
    Category.INFORMATION: N_("Information"),
    Category.RESOURCES: N_("Resources"),
    Category.BASELINE: N_("Baseline"),
}


def _category_label(category: Category) -> str:
    return _(_CATEGORY_LABELS[category])


def _game_beat_label(code: str) -> str:
    return _(_GAME_BEAT_LABELS[code])


def _game_beat_definition(code: str) -> str | None:
    label = _GAME_BEAT_LABELS[code]
    if label not in _GAME_BEAT_DEFINITIONS:
        return None
    return _(_GAME_BEAT_DEFINITIONS[label])


def _matchup_label(f: Finding) -> str:
    if f.code in _MATCHUP_LABELS:
        return _(_MATCHUP_LABELS[f.code])
    return _category_label(f.category)


def _cause_heading(cause: str) -> str:
    return _(_CAUSE_HEADINGS[cause])


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
    turn_number: int | None = None  # the source finding's own, player-turn
    definition: str | None = None  # the label's one sentence; None when it has none


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


def _reason_text(reason: str | None, result: str | None) -> str | None:
    if not reason:
        return None
    key = (reason, result if result in ("loss", "win") else None)
    if key not in _RESULT_REASON_WORDS:
        return None
    return _(_RESULT_REASON_WORDS[key])


def _evidence(f: Finding, key: str) -> int | float | str | bool | None:
    return next((e.value for e in f.evidence if e.key == key), None)


def _matchup_beat(f: Finding) -> Beat:
    return Beat(
        code=f.code,
        label=_matchup_label(f),
        text=f.title,
        magnitude=None,
        severity=f.severity,
        game_number=None,
        turn_number=f.turn_number,
    )


def _game_beat(f: Finding) -> Beat:
    label = _game_beat_label(f.code)
    meter: tuple[float, float] | None = None
    magnitude: str | None = None
    text = f.title

    if f.code in _RACE_CODES:
        self_dealt = _evidence(f, "self_damage_dealt")
        opp_dealt = _evidence(f, "opp_damage_dealt")
        if isinstance(self_dealt, int | float) and isinstance(opp_dealt, int | float):
            text = _("{ours} to {theirs}").format(
                ours=decimal(self_dealt), theirs=decimal(opp_dealt))
            meter = (float(self_dealt), float(opp_dealt))
    elif f.code == "turning_point":
        drop = _evidence(f, "drop")
        if isinstance(drop, int | float):
            magnitude = swing_words(drop)
            text = (_("your turn {turn} · {magnitude}").format(
                        turn=f.self_turn_index, magnitude=magnitude)
                    if f.self_turn_index else magnitude)
    elif f.code == "cards_stranded_in_a_loss":
        stranded = _evidence(f, "stranded_cards")
        if stranded is not None:
            text = ngettext("{n} cards left in hand", "{n} cards left in hand",
                            int(stranded)).format(n=stranded)
    elif f.code == "beatdown_held_back":
        held = _evidence(f, "turns_held_back")
        if held is not None:
            text = ngettext("held back {n}x", "held back {n}x", int(held)).format(n=held)
    elif f.code == "over_committed_into_sweeper":
        peak = _evidence(f, "peak_permanents")
        if peak is not None:
            text = ngettext("{n} permanents, sweeper unaccounted for",
                            "{n} permanents, sweeper unaccounted for",
                            int(peak)).format(n=peak)

    return Beat(
        code=f.code, label=label, text=text, magnitude=magnitude,
        severity=f.severity, game_number=f.game_number, meter=meter,
        turn_number=f.turn_number, definition=_game_beat_definition(f.code),
    )


def _beat_candidates(findings: list[Finding]) -> list[Finding]:
    return sorted(
        (f for f in findings if f.code in _GAME_BEAT_LABELS),
        key=lambda f: _SEVERITY_RANK.get(f.severity, 9),
    )


def _game_line(game: GameFacts, findings: list[Finding]) -> GameLine:
    candidates = _beat_candidates(findings)
    beats = tuple(_game_beat(f) for f in candidates[:_MAX_BEATS_PER_GAME])
    return GameLine(
        game_number=game.game_number,
        result=game.result,
        result_reason_text=_reason_text(game.result_reason, game.result),
        turn_count=game.turn_count,
        on_play=game.on_play,
        self_mulligans=game.self_mulligans,
        beats=beats,
    )


def _headline(report: MatchReport) -> str:
    opponent = report.opponent_label or _("an unidentified opponent")
    wins = sum(1 for g in report.games if g.result == "win")
    losses = sum(1 for g in report.games if g.result == "loss")
    if report.result == "win":
        return _("Won {wins}\u2013{losses} vs {opponent}").format(
            wins=wins, losses=losses, opponent=opponent)
    if report.result == "loss":
        return _("Lost {wins}\u2013{losses} to {opponent}").format(
            wins=wins, losses=losses, opponent=opponent)
    if report.result == "draw":
        return _("Drew {wins}\u2013{losses} with {opponent}").format(
            wins=wins, losses=losses, opponent=opponent)
    return _("Match vs {opponent} is not yet complete").format(opponent=opponent)


def _lost_game_cause(game_number: int, findings: list[Finding]) -> str:
    top = next((f for f in _beat_candidates(findings) if f.code not in _NOT_A_CAUSE), None)
    if top is None:
        return _("Game {n}: no single cause stood out.").format(n=game_number)
    beat = _game_beat(top)
    return _("Game {n}, {label}: {text}.").format(n=game_number, label=beat.label,
                                                  text=beat.text)


def _race_mismatch_subhead(report: MatchReport,
                           findings_by_game: dict[int, list[Finding]]) -> str | None:
    """You led the race in every game and still lost some. Every number
    here is a count of ``report.games``/``.findings``, a lost game's number,
    or a number the beat it names already carries."""
    total = len(report.games)
    if total == 0:
        return None
    race_ahead_games = {f.game_number for f in report.findings if f.code == "race_ahead"}
    lost_games = {g.game_number for g in report.games if g.result == "loss"}
    if not lost_games or len(race_ahead_games) != total or not (race_ahead_games & lost_games):
        return None
    n_lost = len(lost_games)
    opening = ngettext(
        "You led the damage race in all {total} games and still lost {n} game.",
        "You led the damage race in all {total} games and still lost {n} games.",
        n_lost,
    ).format(total=total, n=n_lost)
    causes = [_lost_game_cause(n, findings_by_game.get(n, [])) for n in sorted(lost_games)]
    return " ".join([opening, *causes])


def _subhead(report: MatchReport, findings_by_game: dict[int, list[Finding]]) -> str | None:
    mismatch = _race_mismatch_subhead(report, findings_by_game)
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
    groups = [GapGroup(cause=_cause_heading(c), blocked=tuple(grouped[c])) for c in order]
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
        subhead=_subhead(report, findings_by_game),
        matchup=tuple(_matchup_beat(f) for f in matchup_findings),
        games=tuple(
            _game_line(game, findings_by_game.get(game.game_number, []))
            for game in report.games
        ),
        gap_groups=_group_gaps(report.gaps),
    )
