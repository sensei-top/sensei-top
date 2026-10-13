"""The structured types every analyzer emits, and the report they roll up
into.

Two of these carry the design's honesty rules:

* ``Confidence`` and ``Gap`` are how rule 4 ("never synthesize data") shows
  up in code. An analyzer that cannot see what it needs emits a ``Gap``
  saying so, or emits nothing at all — it never guesses. A ``Gap`` is not a
  low-confidence ``Finding``; it is the absence of one, said out loud, kept
  in its own list so silence is never mistaken for "nothing was wrong".
* ``Evidence.key`` and ``Finding.code`` are stable identifiers, not prose.
  Phase B's aggregate rollup (not built yet) groups on ``code`` and averages
  ``evidence[key]`` across matches — renaming either silently breaks a trend
  that Phase B would otherwise report cleanly.

Every field here is a scalar or a tuple of scalars, so if these are ever
persisted (they are not — see ``review/__init__.py`` for why), ``Finding``
is one flat row and ``Evidence`` a child table with no reshaping needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Category(StrEnum):
    """The arc a postmortem reads in: the matchup and the role it demands,
    who was winning the race, the shape of the whole game, whether the
    assigned role was actually played, what hidden information was still
    live, the resource trade, and how this compares to a wider sample."""

    FRAME = "frame"          # the matchup, and who has to be the beatdown
    CLOCK = "clock"          # damage racing: who is killing whom, and how fast
    TRAJECTORY = "trajectory"   # the position index and the turning point
    ROLE = "role"           # did the assigned role actually get played
    INFORMATION = "information"  # what the opponent's consensus list says was still live
    RESOURCES = "resources"     # card advantage, counters, trades
    BASELINE = "baseline"      # this game against your own history and the field's


class Severity(StrEnum):
    """Not "how bad" in the abstract — a tracker reading a log still has no
    business grading a play as a major error from vibes. ``DECISIVE`` is
    reserved for the two findings that name what actually decided the game
    (the turning point, the race verdict) and only fires when the evidence
    chain behind it is complete; ``FLAG`` is a directly-observed fact a
    reasonable player would want to know; ``NOTICE`` is a thing that
    happened and is sometimes a mistake and sometimes correct play; ``NOTE``
    is context with no judgement implied at all."""

    NOTE = "note"
    NOTICE = "notice"
    FLAG = "flag"
    DECISIVE = "decisive"


class Confidence(StrEnum):
    OBSERVED = "observed"   # every input this finding rests on was directly observed
    PARTIAL = "partial"    # some input was NULL, hidden, or otherwise ambiguous


@dataclass(frozen=True, slots=True)
class Evidence:
    """One named number (or short string) a finding was computed from.

    Every number that appears in a ``Finding``'s ``title`` or ``detail``
    must appear here too, or equal the finding's own ``game_number`` /
    ``turn_number`` / ``self_turn_index`` — see
    ``tests/test_review.py::test_no_finding_cites_a_number_it_cannot_show``.
    A number in prose with nothing backing it is, by construction, a number
    the analyzer invented.
    """

    key: str
    label: str
    value: int | float | str | bool | None
    unit: str | None = None
    display: str | None = None  # a human phrase for `value`, e.g. "0.49 — a decisive swing";
    # `value` itself stays the raw number a rollup groups on — this is presentation only.


@dataclass(frozen=True, slots=True)
class Finding:
    code: str                          # stable across matches; a rollup groups on this
    analyzer: str
    category: Category
    severity: Severity
    confidence: Confidence
    title: str                         # one clause, no numbers the evidence does not carry
    detail: str                        # one or two sentences of exactly what was observed
    game_number: int | None = None     # None = the whole match
    turn_number: int | None = None     # player-turn, matching turns.turn_number
    self_turn_index: int | None = None  # "your Nth turn" — see v_self_turns
    evidence: tuple[Evidence, ...] = ()
    caveats: tuple[str, ...] = ()      # what would change this reading if it were observable
    pattern: str | None = None         # this code's own cross-match name, for the leak finder;
    # None means "not a leak candidate" — opt-in by design, so a new analyzer never silently
    # enters the ranking. See leaks.py, which filters and titles rows on this field alone.


@dataclass(frozen=True, slots=True)
class Gap:
    """What an analyzer could not evaluate, and why — never mixed into
    findings, so the dashboard and the narrative can both render "what this
    report could not see" as its own block rather than silence."""

    analyzer: str
    reason: str
    game_number: int | None = None
    cause: str | None = None  # a stable slug shared by gaps with one real root cause
    # (e.g. "opponent_unclassified") — summary.py groups on this so four analyzers
    # independently blocked by the same absence render as one heading, not four.


@dataclass(frozen=True, slots=True)
class AnalyzerResult:
    findings: tuple[Finding, ...] = ()
    gaps: tuple[Gap, ...] = ()


@dataclass(frozen=True, slots=True)
class GameFacts:
    """The bare per-game facts every analyzer starts from — a thin read of
    ``games``, nothing derived."""

    game_number: int
    on_play: bool | None
    result: str | None
    result_reason: str | None
    turn_count: int | None
    self_mulligans: int | None
    opp_mulligans: int | None


@dataclass(frozen=True, slots=True)
class MatchReport:
    match_id: str
    deck_id: str | None
    result: str | None
    games: tuple[GameFacts, ...] = field(default_factory=tuple)
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    gaps: tuple[Gap, ...] = field(default_factory=tuple)
    opponent_label: str | None = None
