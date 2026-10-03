"""Decoded MTGO strings -> structured events.

Stage 2 only (AGENTS.md non-negotiable #1): this module knows the grammar of
MTGO's own text, and nothing about files, bytes, or self/opponent —
``decode.py`` hands it already-decoded strings, and ``project.py`` is the
only place that knows which handle is "us" and writes rows to a database.

Grammar recognised (every shape confirmed present in the fixture; see
``.claude/handoffs/mtgo-implementation.md``'s table and the Live MTGO matches
plan's Bug B analysis):

* the bare GUID appearing as (one of) the first decoded string(s) -> match id
* ``<H> rolled a <n>.`` -> discovers a handle (the pre-game die roll)
* ``<H> joined the game.`` -> a game-boundary signal (see below)
* ``<H> chooses to play first.`` -> on_play for the game being started
* ``<H> mulligans to <n> cards.`` -> a mulligan count for the game being
  started (``<n>`` is spelled out as a word in the real fixture — ``"six"``,
  not ``"6"`` — so both forms are accepted)
* ``<H> begins the game with <n> cards in hand.`` (also
  ``<H> puts a card on the bottom of their library and begins the game with
  <n> cards in hand.`` — both shapes are in the fixture) -> the
  **authoritative** mulligan count for that handle in the game being started:
  ``mulligans = 7 - n``. Present for *every* player in *every* game,
  including a kept 7 (which emits no ``mulligans to`` line at all) — this is
  what makes it authoritative rather than ``mulligans to``, which is silent
  on a keep.
* ``Turn <n>: <H>`` -> turn number + active handle. **Not** the primary
  game-boundary signal (see Bug B below) — a fallback only.
* ``<H> plays @[Name@:i1,i2:@].`` -> a card event, category ``PlayLand``
  (MTG's own rules vocabulary: you *play* a land, never a spell — so this
  verb alone tells us the category, matching Arena's own ``PlayLand``
  annotation category without needing separate evidence)
* ``<H> casts @[Name@:i1,i2:@].`` -> a card event, category ``CastSpell``
  (same reasoning, and again matches Arena's own vocabulary)
* ``<H> activates an ability of @[Name@:i1,i2:@] ...`` -> a card event,
  category ``Activate`` (MTGO-only vocabulary; Arena's annotation categories
  have no equivalent single tag for this, so this parser mints one rather
  than reusing a category that would imply zone/annotation semantics MTGO's
  log doesn't carry)
* ``<H> puts a triggered ability from @[Name@:i1,i2:@] onto the stack ...``
  -> a card event, category ``Trigger`` (same reasoning as ``Activate``)
* ``<H> has conceded from the game.`` -> the current game's result reason
* ``<H> wins the game.`` -> the current game's winning handle
* ``<H> leads the match <a>-<b>`` / ``<H> wins the match <a>-<b>`` -> a
  running or final score, recorded as ``ParsedMatch.score_line`` (a
  **self-check only** — see below); only ``wins the match`` sets the
  authoritative ``winner_handle``.

Deliberately **not** parsed, even though real and present in the fixture:
``draws a card``, ``discards``, ``is being attacked by``, ``creates a ...
Token``, ``chooses <color> for`` — none of these appear in the plan's
grammar table, and every card name in the one real sample already surfaces
through the plays/casts/activates/triggers lines above (verified: 26 distinct
``@[...]`` names in the fixture, all 26 reachable through just those four
line shapes).

Bug B — game boundaries are per-game start markers, not "turn resets to 1"
---------------------------------------------------------------------------
MTGO numbers turns **per player**, not globally: a single real game emits
both ``Turn 1: <H1>`` and ``Turn 1: <H2>`` (each player's own first turn).
The previous version of this parser treated *every* ``Turn 1: <H>`` line as
"a new game started", which double-counted every real game into two —
confirmed by running the real decoder+parser against
``tests/fixtures/mtgo_match_session.log`` and finding 4 ``GameRecord``s for a
match that is provably 2 games (``tests/test_projector_mtgo.py``). Worse, the
*real* pre-game facts (who's on the play, who mulliganed) landed on the
phantom second-turn "game" rather than the real one, and the parser raised no
warning — exactly the two facts this live feature exists to show.

The fix: every real game in the fixture is preceded by an explicit start
block — ``joined the game`` (both handles), then ``chooses to play first``,
then ``begins the game with <n> cards in hand`` (both handles, always) and
optionally ``mulligans to <n> cards`` — and all of it happens *before* that
game's first ``Turn 1:`` line. So a new ``GameRecord`` starts on the first of
those four start-block signals seen after the previous game already has some
action recorded (``GameRecord.has_action()``), not on ``Turn 1``.
``Turn 1: <H>`` remains a **fallback** boundary — only for a prefix whose
start block was lost (a decode resync landing mid-game, or a truncated live
read) — gated on ``current is None or current.turn_count >= 2`` so that the
*second* player's ``Turn 1`` within one real game does not retrigger it: the
gate reads ``turn_count`` *before* counting the line being processed, and at
that point only the first player's own ``Turn 1`` has been counted, so
``turn_count`` is still 1. The gate reads the printed ``N`` off the line
(``turn_number == 1``), never the ordinal ``turn_count`` stores (see "Turn
units" below). Because ``turn_count`` counts lines, it is already 2 once both
players' ``Turn 1`` lines are in, so a bare ``Turn 1`` as a game's third
``Turn`` line — a real next game whose start block was lost — trips the
fallback at once.

⚠️ These rules rest on a **single fixture**. "``joined the game`` is
per-game" is read off one real match; a mid-game reconnect might emit an
extra ``joined`` line that this parser would misread as a new game. If that
turns out to happen, tighten the rule to "both handles have (re-)joined since
the last boundary" rather than "either handle joined once".

Turn units — this parser's ``turn_count``/``turn_number`` are Arena's units,
not MTGO's printed ones
-------------------------------------------------------------------------
MTGO's own log *prints* turn numbers per player (``Turn 1: <H1>``,
``Turn 1: <H2>``, ``Turn 2: <H1>``…), but ``GameRecord.turn_count`` and
``CardEvent.turn_number`` do **not** store that printed number — they count
**player-turns globally**, the same unit Arena's own ``turnNumber`` already
uses (``projector/matches.py``: 1 (you), 2 (them), 3 (you)…), so a consumer
that pools both sources (the coach, ``v_deck_game_length``,
``review/analyzers/baseline.py``, ``guide/play.py``) reads one unit, not two.
Concretely: each ``Turn N: <H>`` *line* is one player-turn, so
``turn_count`` is the count of ``Turn`` lines seen in the game so far (not
the highest printed ``N``), and a card event's ``turn_number`` is that same
running count at the moment the event was parsed — an ordinal, reset to 0
every time a new ``GameRecord`` starts (``ensure_fresh_game``) so that a card
event between a new game's start block and its own first ``Turn`` line gets
``turn_number=None`` rather than inheriting the previous game's last count
(the same class of bug Bug B fixed for game boundaries, applied here to the
per-event field). A game with only ``Turn 1: <H1>`` and ``Turn 1: <H2>`` —
two lines, one per player — therefore has ``turn_count == 2``, not ``1``.

``score_line`` is deliberately self-check only: ``games_won``/``games_lost``
are always derived by *counting* ``GameRecord.winner_handle`` values
(``project.py``), never by trusting the match-score text. ``leads the match``
and ``wins the match`` share the same ``<a>-<b>`` shape and both update
``score_line`` (last one seen wins) so the check has something to compare
against even for a match that ends before either side would say "leads";
only ``wins the match`` — never ``leads the match`` — sets the authoritative
``winner_handle``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ROLLED_RE = re.compile(r"^(?P<handle>\S+) rolled a \d+\.$")
_JOINED_RE = re.compile(r"^(?P<handle>\S+) joined the game\.$")
_PLAY_FIRST_RE = re.compile(r"^(?P<handle>\S+) chooses to play first\.$")
_MULLIGAN_RE = re.compile(r"^(?P<handle>\S+) mulligans to (?P<n>\w+) cards?\.$")
# `.*?` (non-greedy) is required by the fixture's two shapes: line "<H>
# begins the game with seven cards in hand." (plain) and "<H> puts a card on
# the bottom of their library and begins the game with six cards in hand."
# (after a mulligan) — both end the same way, only the middle differs.
# The handle ends at a literal space, never `\b`: a handle ending in a
# non-word character ("Name-") has no word boundary before that space, so
# `\S+\b` backtracked to "Name" — a third, phantom handle that made
# `project_mtgo` skip the whole match (real match, 2026-09-22).
_BEGINS_RE = re.compile(
    r"^(?P<handle>\S+) .*?begins the game with (?P<n>\w+) cards? in hand\.$"
)
_TURN_RE = re.compile(r"^Turn (?P<n>\d+): (?P<handle>\S+)$")
_CONCEDE_RE = re.compile(r"^(?P<handle>\S+) has conceded from the game\.$")
_WINS_GAME_RE = re.compile(r"^(?P<handle>\S+) wins the game\.$")
_WINS_MATCH_RE = re.compile(r"^(?P<handle>\S+) wins the match \d+-\d+$")
# Self-check only (see module docstring): both "leads the match" (running,
# mid-match) and "wins the match" (final) carry the same score shape, so both
# feed `score_line` even though only the latter sets `winner_handle`.
_LEADS_MATCH_RE = re.compile(
    r"^(?P<handle>\S+) (?:leads|wins) the match (?P<a>\d+)-(?P<b>\d+)$"
)

_CARD_REF = r"@\[(?P<name>[^@]+)@:\d+,\d+:@\]"
_PLAYS_RE = re.compile(rf"^(?P<handle>\S+) plays {_CARD_REF}\.$")
_CASTS_RE = re.compile(rf"^(?P<handle>\S+) casts {_CARD_REF}\.$")
_ACTIVATES_RE = re.compile(rf"^(?P<handle>\S+) activates an ability of {_CARD_REF}")
_TRIGGER_RE = re.compile(
    rf"^(?P<handle>\S+) puts a triggered ability from {_CARD_REF} onto the stack"
)
_CARD_EVENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PlayLand", _PLAYS_RE),
    ("CastSpell", _CASTS_RE),
    ("Activate", _ACTIVATES_RE),
    ("Trigger", _TRIGGER_RE),
)

_WORD_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                  "six": 6, "seven": 7}


def _parse_number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _WORD_NUMBERS.get(token.lower())


def _strip_at_p_prefix(s: str) -> str:
    """Strip one or more leading ``@P`` markers. Real content, not framing
    noise (recon: ``"player handles as @PHandle"``) — some lines carry it
    twice (``"@P@PPlayer1 joined the game."``), most once; the marker's own
    repeat count carries no signal this parser needs.
    """
    while s.startswith("@P"):
        s = s[2:]
    return s


@dataclass
class CardEvent:
    handle: str
    category: str
    name: str
    # Arena's units (see module docstring's "Turn units" section): the
    # running count of `Turn` lines seen in this game so far, not MTGO's own
    # printed per-player number. None when no `Turn` line has been seen yet
    # in this game (before the game's own first turn, or no game at all).
    turn_number: int | None


@dataclass
class GameRecord:
    game_number: int
    on_play_handle: str | None = None
    mulligans_by_handle: dict[str, int] = field(default_factory=dict)
    # Arena's units, not MTGO's printed ones (module docstring's "Turn
    # units"): the count of `Turn` lines seen in this game, i.e. total
    # player-turns, not the highest printed per-player N.
    turn_count: int = 0
    winner_handle: str | None = None
    conceded_handle: str | None = None
    card_events: list[CardEvent] = field(default_factory=list)

    def has_action(self) -> bool:
        """True once this game has recorded anything beyond the pre-game
        start block — used to decide whether a new start-block signal begins
        a *new* game or merely fills in the still-empty current one (the
        start block is several lines wide: ``joined``, ``chooses to play
        first``, ``begins the game with``, an optional ``mulligans to``, all
        before that game's first real turn)."""
        return bool(
            self.turn_count or self.card_events
            or self.winner_handle or self.conceded_handle
        )


@dataclass
class ParsedMatch:
    match_id: str | None
    handles: set[str]
    games: list[GameRecord]
    winner_handle: str | None   # from the final "wins the match" line
    score_line: tuple[str, int, int] | None   # self-check only; see docstring
    warnings: list[str]


def _start_new_game(games: list[GameRecord]) -> GameRecord:
    record = GameRecord(game_number=len(games) + 1)
    games.append(record)
    return record


def parse_strings(strings: list[str]) -> ParsedMatch:
    """Turn one MTGO game log's decoded strings into structured events.

    Never raises: an unrecognised string is skipped (see the "deliberately
    not parsed" list in the module docstring) rather than treated as an
    error — MTGO's log carries plenty of real content this parser has no use
    for yet.
    """
    match_id: str | None = None
    handles: set[str] = set()
    games: list[GameRecord] = []
    current: GameRecord | None = None
    current_turn: int | None = None
    final_winner: str | None = None
    score_line: tuple[str, int, int] | None = None
    warnings: list[str] = []

    def ensure_fresh_game() -> None:
        """Start a new GameRecord for a start-block signal, unless the
        current one is still the empty shell an earlier start-block signal
        already created for this same game. Resets the per-game turn
        ordinal (``current_turn``) on an actual new game so a card event
        seen before the new game's own first ``Turn`` line gets
        ``turn_number=None`` rather than inheriting the previous game's last
        count (module docstring's "Turn units")."""
        nonlocal current, current_turn
        if current is None or current.has_action():
            current = _start_new_game(games)
            current_turn = None

    for raw in strings:
        if match_id is None and _GUID_RE.match(raw):
            match_id = raw
            continue
        s = _strip_at_p_prefix(raw)

        m = _ROLLED_RE.match(s)
        if m:
            handles.add(m.group("handle"))
            continue

        m = _JOINED_RE.match(s)
        if m:
            handles.add(m.group("handle"))
            ensure_fresh_game()
            continue

        m = _PLAY_FIRST_RE.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            ensure_fresh_game()
            current.on_play_handle = handle
            continue

        m = _MULLIGAN_RE.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            kept = _parse_number(m.group("n"))
            if kept is None:
                warnings.append(f"unrecognised mulligan count in {s!r}")
            else:
                ensure_fresh_game()
                current.mulligans_by_handle[handle] = 7 - kept
            continue

        m = _BEGINS_RE.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            kept = _parse_number(m.group("n"))
            if kept is None:
                warnings.append(f"unrecognised hand size in {s!r}")
            else:
                ensure_fresh_game()
                authoritative = 7 - kept
                existing = current.mulligans_by_handle.get(handle)
                if existing is not None and existing != authoritative:
                    warnings.append(
                        f"mulligan count mismatch for {handle}: "
                        f"'mulligans to' implied {existing}, "
                        f"'begins the game' implied {authoritative} ({s!r})"
                    )
                current.mulligans_by_handle[handle] = authoritative
            continue

        m = _TURN_RE.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            # The printed per-player number — used only by the fallback gate
            # below, never stored. See the module docstring's "Turn units":
            # what gets stored is an ordinal count of `Turn` lines, Arena's
            # own units, not this raw MTGO number.
            turn_number = int(m.group("n"))
            if turn_number == 1 and (current is None or current.turn_count >= 2):
                # Fallback boundary only: the primary signal is the start
                # block above. Firing here means that block was never seen
                # (lost to a decode resync, or a truncated live read) — flag
                # it rather than let a second silent double-count happen.
                warnings.append(
                    f"game boundary inferred from 'Turn 1' with no preceding "
                    f"start block ({s!r})"
                )
                current = _start_new_game(games)
            if current is not None:
                # One `Turn` line = one player-turn (Arena's units): count
                # lines, don't track the printed N's own max.
                current.turn_count += 1
                current_turn = current.turn_count
            else:
                current_turn = None
            continue

        matched_card_event = False
        for category, pattern in _CARD_EVENT_PATTERNS:
            m = pattern.match(s)
            if not m:
                continue
            matched_card_event = True
            handle = m.group("handle")
            handles.add(handle)
            if current is None:
                warnings.append(f"card event before any game started: {s!r}")
            else:
                current.card_events.append(
                    CardEvent(
                        handle=handle, category=category,
                        name=m.group("name"), turn_number=current_turn,
                    )
                )
            break
        if matched_card_event:
            continue

        m = _CONCEDE_RE.match(s)
        if m:
            handles.add(m.group("handle"))
            if current is not None:
                current.conceded_handle = m.group("handle")
            continue

        m = _WINS_GAME_RE.match(s)
        if m:
            handles.add(m.group("handle"))
            if current is not None:
                current.winner_handle = m.group("handle")
            continue

        m = _WINS_MATCH_RE.match(s)
        if m:
            handles.add(m.group("handle"))
            final_winner = m.group("handle")
            # falls through to _LEADS_MATCH_RE below so the same line also
            # updates score_line — don't `continue` here.

        m = _LEADS_MATCH_RE.match(s)
        if m:
            handles.add(m.group("handle"))
            score_line = (m.group("handle"), int(m.group("a")), int(m.group("b")))
            continue

        # Anything else is real MTGO text this parser has no use for yet
        # (see the module docstring's "deliberately not parsed" list) — not
        # a warning.

    return ParsedMatch(
        match_id=match_id, handles=handles, games=games,
        winner_handle=final_winner, score_line=score_line, warnings=warnings,
    )
