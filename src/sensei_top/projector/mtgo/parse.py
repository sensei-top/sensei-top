"""Decoded MTGO strings -> structured events.

Stage 2 only (AGENTS.md non-negotiable #1): this module knows the grammar of
MTGO's own text, and nothing about files, bytes, or self/opponent —
``decode.py`` hands it already-decoded strings, and ``project.py`` is the
only place that knows which handle is "us" and writes rows to a database.
The one entry point that takes bytes, ``last_game_decided``, hands them
straight to ``decode.py`` (see "Whether the last game is decided" below).

Grammar recognised. The fixture holds the start block, the turns, the card
lines, the concessions, the wins and the match lines; the ending, reconnect
and watching lines come from the real history plan 30 measured
(2026-10-19), and ``tests/test_projector_mtgo.py`` carries them as
transcribed lines. ``<H>`` is a handle, read as "Handles" below says:

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
  (``concede``)
* ``<H> loses the game.`` -> the current game's losing handle
* ``<H> has lost the game due to inaction.`` -> the current game's losing
  handle, reason ``inaction``
* ``<H> has run out of time and has lost the match.`` -> the current game's
  losing handle, reason ``timeout``, and the match's loser: when no
  ``wins the match`` line follows, the other player wins the match
* ``<A> and <B> lose the game.`` -> the current game is a draw
* ``<H> wins the game.`` -> the current game's winning handle. A ``wins``
  line that contradicts a loss line or a draw leaves the game with no
  result, and a warning
* ``<H> has lost connection to the game.`` -> a drop; that handle's next
  ``joined the game`` in the same game is a rejoin (see Bug B below)
* ``<H> has started watching.`` -> a spectator, kept in
  ``ParsedMatch.spectators`` and never among the players
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
line shapes). Nor are ``Match Tied <a>-<b>``, MTGO's running score while the
match is level (``score_line`` would be its only reader, and it is a
self-check, see below), or ``has left the game``: a game that ends with a
player leaving, or with a lost connection and no return, has no result here,
since the log never says who MTGO awarded it to.

Handles
-------
A handle may hold a space (``Player Two``), so ``<H>`` is not ``\\S+``. The
players' handles come first from the lines whose ending is fixed
(``rolled a <n>.``, ``joined the game.``, ``chooses to play first.``), where
everything before that ending is the handle; a spectator's come from
``has started watching.`` and are kept apart. Every other line is read as
led by one of the players' handles, longest first, then a space, so
``Bob Two`` is tried before ``Bob``. A transcript with none of those lines
falls back to ``\\S+``. Two opponents in the real history had a space in
their handle, and both matches read wrong before this rule.

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

A reconnect is not a new game. A player who drops writes ``<H> has lost
connection to the game.`` and, on return, ``<H> joined the game.`` again in
the middle of the game; MTGO keeps counting its turns and re-sends no start
block. So a ``joined`` by a handle that lost connection earlier in the
current, undecided game is a rejoin: no new game, nothing stored, a debug
line. The set of such handles lasts the whole game (a player can drop
twice); a drop is ignored once the game has a result, and the set is
emptied when the next game opens. Every other ``joined`` opens a game as
above, and opening one while the last has action and no result warns that
a game started before the last one ended. Before this rule, the real
history held 9 phantom games in 8 matches, each pushing every later game
of its match one number up.

A concession inside a start block
---------------------------------
A player can concede in the middle of their own mulligan, and MTGO still
writes the rest of that game after the concession. One real game reads
``mulligans to five cards``, ``has conceded from the game``, then the same
player's ``puts two cards on the bottom of their library and begins the game
with five cards in hand.``, their ``Turn 1``, and the opponent's ``wins the
game``. The concession counts as action (``has_action()``), so that
``begins`` line opened a second game, which took the turn and the win and
left the first with no result. So only ``joined``, the line that opens a
start block, starts a new game after a bare concession; ``chooses to play
first``, ``mulligans to`` and ``begins the game with`` start one only once
the current game has a turn, a card event or a result
(``GameRecord.has_begun()``). A ``joined`` after a concession with no result
line still opens the next game, with the warning above.

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
are always derived by *counting* each game's result as
``project.py::_game_outcome`` reads it (its winner, else the loser's
opponent), never by trusting the match-score text. ``leads the match``
and ``wins the match`` share the same ``<a>-<b>`` shape and both update
``score_line`` (last one seen wins) so the check has something to compare
against even for a match that ends before either side would say "leads";
only ``wins the match`` — never ``leads the match`` — sets the authoritative
``winner_handle``.

Whether the last game is decided
--------------------------------
The watcher stores a game log once a game ends (plan 3, D2; ``live.py``), and
"has a game ended" is a question about what the text means, so the reader
cannot answer it (``reader/mtgo.py``'s module docstring): ``last_game_decided``
answers it here, from the same decode and parse ``project.py`` uses, so the
watcher judges a file by the reading the projector will give it.

Decided means the last ``GameRecord`` names a winner (``<H> wins the
game.``), a loser (``loses the game.``, ``has lost the game due to
inaction.``, ``has run out of time and has lost the match.``) or a draw
(``<A> and <B> lose the game.``). A concession alone does not count: both of
the fixture's games write ``has conceded from the game`` and then ``wins the
game`` as two strings, and a read can land between them. The next game's
first start-block line (``joined the game``) opens a new record, so between
games the answer stays true until that line lands, then false until the new
game names a winner, a loser or a draw. A game that ends with none of these
(a disconnect, a crash) is never decided here; the watcher's 10-minute quiet
fallback stores it. Since only a complete string can match the grammar, a
read cut mid-string (MTGO's own write, or a copy's, half done) loses the
string at the cut rather than deciding anything from it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sensei_top.projector.mtgo.decode import decode_strings

log = logging.getLogger(__name__)

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_CARD_REF = r"@\[(?P<name>[^@]+)@:\d+,\d+:@\]"

# The handle rule (plan 30, D5). A handle may hold a space ("Player Two"), so
# `\S+` read only its first word. The players' handles are taken first from
# the lines whose ending is fixed, where everything before that ending is the
# handle; every other line's handle is then one of those, longest first, so
# "Bob Two" is tried before "Bob". A transcript with none of these lines
# falls back to `\S+`, and with them, a line led by any other handle matches
# nothing.
_PLAYER_HANDLE_RES = (
    re.compile(r"^(?P<handle>.+) rolled a \d+\.$"),
    re.compile(r"^(?P<handle>.+) joined the game\.$"),
    re.compile(r"^(?P<handle>.+) chooses to play first\.$"),
)
# A spectator's handle, kept apart from the players': a spectator writes
# nothing but this line, so no other line needs reading as theirs, and
# `project.py` skips any match with other than exactly one opponent, so a
# spectator counted as a player would lose the user's own match.
_WATCHING_RE = re.compile(r"^(?P<handle>.+) has started watching\.$")


def _known_handles(strings: list[str]) -> tuple[set[str], set[str]]:
    """The players and the spectators the fixed-suffix lines name."""
    players: set[str] = set()
    spectators: set[str] = set()
    for raw in strings:
        s = _strip_at_p_prefix(raw)
        for pattern in _PLAYER_HANDLE_RES:
            m = pattern.match(s)
            if m:
                players.add(m.group("handle"))
                break
        else:
            m = _WATCHING_RE.match(s)
            if m:
                spectators.add(m.group("handle"))
    return players, spectators


def _handle_alternation(known: set[str]) -> str:
    """The regex a handle is read with: the known handles, escaped, longest
    first (ties alphabetical, so the order is stable), or ``\\S+`` with
    none."""
    if not known:
        return r"\S+"
    ordered = sorted(known, key=lambda h: (-len(h), h))
    return "|".join(re.escape(h) for h in ordered)


@dataclass(frozen=True)
class _Patterns:
    """Every pattern that reads a handle, built once per transcript from its
    handles (``_patterns``)."""

    rolled: re.Pattern[str]
    joined: re.Pattern[str]
    lost_connection: re.Pattern[str]
    play_first: re.Pattern[str]
    mulligan: re.Pattern[str]
    begins: re.Pattern[str]
    turn: re.Pattern[str]
    concede: re.Pattern[str]
    loses_game: re.Pattern[str]
    inaction: re.Pattern[str]
    timeout: re.Pattern[str]
    draw: re.Pattern[str]
    wins_game: re.Pattern[str]
    wins_match: re.Pattern[str]
    leads_match: re.Pattern[str]
    card_events: tuple[tuple[str, re.Pattern[str]], ...]


def _patterns(known: set[str]) -> _Patterns:
    # The handle ends at a literal space, never `\b`: a handle ending in a
    # non-word character ("Name-") has no word boundary before that space, so
    # `\S+\b` backtracked to "Name" — a third, phantom handle that made
    # `project_mtgo` skip the whole match (real match, 2026-09-22).
    alternation = _handle_alternation(known)
    h = f"(?P<handle>{alternation})"
    return _Patterns(
        rolled=re.compile(rf"^{h} rolled a \d+\.$"),
        joined=re.compile(rf"^{h} joined the game\.$"),
        lost_connection=re.compile(rf"^{h} has lost connection to the game\.$"),
        play_first=re.compile(rf"^{h} chooses to play first\.$"),
        mulligan=re.compile(rf"^{h} mulligans to (?P<n>\w+) cards?\.$"),
        # `.*?` (non-greedy) is required by the fixture's two shapes: line
        # "<H> begins the game with seven cards in hand." (plain) and "<H>
        # puts a card on the bottom of their library and begins the game with
        # six cards in hand." (after a mulligan) — both end the same way,
        # only the middle differs.
        begins=re.compile(
            rf"^{h} .*?begins the game with (?P<n>\w+) cards? in hand\.$"
        ),
        turn=re.compile(rf"^Turn (?P<n>\d+): {h}$"),
        concede=re.compile(rf"^{h} has conceded from the game\.$"),
        loses_game=re.compile(rf"^{h} loses the game\.$"),
        inaction=re.compile(rf"^{h} has lost the game due to inaction\.$"),
        timeout=re.compile(rf"^{h} has run out of time and has lost the match\.$"),
        # Two handles, so the bare alternation twice: a group name can't repeat.
        draw=re.compile(rf"^(?P<a>{alternation}) and (?P<b>{alternation}) lose the game\.$"),
        wins_game=re.compile(rf"^{h} wins the game\.$"),
        wins_match=re.compile(rf"^{h} wins the match \d+-\d+$"),
        # Self-check only (see module docstring): both "leads the match"
        # (running, mid-match) and "wins the match" (final) carry the same
        # score shape, so both feed `score_line` even though only the latter
        # sets `winner_handle`.
        leads_match=re.compile(
            rf"^{h} (?:leads|wins) the match (?P<a>\d+)-(?P<b>\d+)$"
        ),
        card_events=(
            ("PlayLand", re.compile(rf"^{h} plays {_CARD_REF}\.$")),
            ("CastSpell", re.compile(rf"^{h} casts {_CARD_REF}\.$")),
            ("Activate", re.compile(rf"^{h} activates an ability of {_CARD_REF}")),
            ("Trigger", re.compile(
                rf"^{h} puts a triggered ability from {_CARD_REF} onto the stack"
            )),
        ),
    )


_WORD_NUMBERS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                  "six": 6, "seven": 7}


def _parse_number(token: str) -> int | None:
    if token.isascii() and token.isdigit():
        try:
            return int(token)
        except ValueError:  # more digits than int() converts
            return None
    return _WORD_NUMBERS.get(token.lower())


def _ascii_int(text: str) -> int | None:
    """``text`` as a whole number, or ``None`` unless it is ASCII digits
    ``int()`` accepts (it also takes non-ASCII digits, and refuses more than
    4,300 of them)."""
    if not (text.isascii() and text.isdigit()):
        return None
    try:
        return int(text)
    except ValueError:
        return None


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
    # Whoever a loss line names: ``loses the game.``, ``has lost the game due
    # to inaction.``, ``has run out of time and has lost the match.``. A
    # concession alone does not set it.
    loser_handle: str | None = None
    # ``<A> and <B> lose the game.``
    draw: bool = False
    # How the game ended, when a line says: "concede", "timeout" or
    # "inaction". None for a game played out, whose ``wins the game.`` doesn't
    # say how.
    reason: str | None = None
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
            or self.loser_handle or self.draw
        )

    def has_begun(self) -> bool:
        """``has_action()`` without a bare concession: a turn, a card event
        or a result. A player can concede in the middle of their own
        mulligan, and MTGO still writes the rest of that start block after
        the concession (module docstring's "A concession inside a start
        block")."""
        return bool(self.turn_count or self.card_events or self.has_result())

    def has_result(self) -> bool:
        """True once a line names a winner, a loser or a draw."""
        return bool(self.winner_handle or self.loser_handle or self.draw)

    def contradicts(self) -> bool:
        """True when the game's lines disagree about its result: the same
        handle both won and lost it, or a draw beside a winner or a loser."""
        if self.draw:
            return self.winner_handle is not None or self.loser_handle is not None
        return self.winner_handle is not None and self.winner_handle == self.loser_handle


@dataclass
class ParsedMatch:
    match_id: str | None
    # The players: the handles the fixed-suffix lines name, plus any the
    # `\S+` fallback read. A watching line never adds one: `project.py` skips
    # a match with other than exactly one opponent, so a spectator counted
    # here would lose the user's own match.
    handles: set[str]
    # Whoever wrote "has started watching." (`_WATCHING_RE`), player or not.
    spectators: set[str]
    games: list[GameRecord]
    winner_handle: str | None   # from the final "wins the match" line
    # Who wrote "has run out of time and has lost the match.": they lost the
    # match, so the other player won it even when no "wins the match" follows.
    timed_out_handle: str | None
    score_line: tuple[str, int, int] | None   # self-check only; see docstring
    # Never a handle or a raw line, which names one: project.py logs these,
    # and the log goes into the diagnostics zip a bug report attaches.
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
    handles, spectators = _known_handles(strings)
    patterns = _patterns(handles)
    games: list[GameRecord] = []
    current: GameRecord | None = None
    current_turn: int | None = None
    final_winner: str | None = None
    timed_out: str | None = None
    score_line: tuple[str, int, int] | None = None
    warnings: list[str] = []
    # Handles that lost connection in the current, undecided game: any later
    # `joined` in that game is a rejoin, not a start block.
    lost_connection: set[str] = set()

    def ensure_fresh_game(*, joined: bool = False) -> None:
        """Start a new GameRecord for a start-block signal, unless the
        current one is still the empty shell an earlier start-block signal
        already created for this same game. Resets the per-game turn
        ordinal (``current_turn``) on an actual new game so a card event
        seen before the new game's own first ``Turn`` line gets
        ``turn_number=None`` rather than inheriting the previous game's last
        count (module docstring's "Turn units"). A ``joined`` line opens a
        game after any action, a concession included; the start block's
        later lines only after a turn, a card event or a result (module
        docstring's "A concession inside a start block")."""
        nonlocal current, current_turn
        if current is None or (current.has_action() if joined else current.has_begun()):
            if current is not None and not current.has_result():
                warnings.append(
                    f"game {current.game_number} had no result when the next "
                    f"game started (a game started before the last one ended)"
                )
            current = _start_new_game(games)
            current_turn = None
            lost_connection.clear()

    for raw in strings:
        if match_id is None and _GUID_RE.match(raw):
            match_id = raw
            continue
        s = _strip_at_p_prefix(raw)

        m = patterns.rolled.match(s)
        if m:
            handles.add(m.group("handle"))
            continue

        m = patterns.lost_connection.match(s)
        if m:
            # Not added to `handles`: a spectator's drop must not make them a
            # player (the `\S+` fallback would).
            handle = m.group("handle")
            if current is not None and not current.has_result():
                lost_connection.add(handle)
            continue

        m = patterns.joined.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            if (
                handle in lost_connection
                and current is not None
                and not current.has_result()
            ):
                log.debug("mtgo: a player rejoined game %d", current.game_number)
                continue
            ensure_fresh_game(joined=True)
            continue

        m = patterns.play_first.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            ensure_fresh_game()
            current.on_play_handle = handle
            continue

        m = patterns.mulligan.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            kept = _parse_number(m.group("n"))
            if kept is None:
                warnings.append(f"unrecognised mulligan count {m.group('n')!r}")
            else:
                ensure_fresh_game()
                current.mulligans_by_handle[handle] = 7 - kept
            continue

        m = patterns.begins.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            kept = _parse_number(m.group("n"))
            if kept is None:
                warnings.append(f"unrecognised hand size {m.group('n')!r}")
            else:
                ensure_fresh_game()
                authoritative = 7 - kept
                existing = current.mulligans_by_handle.get(handle)
                if existing is not None and existing != authoritative:
                    warnings.append(
                        f"mulligan count mismatch in game {current.game_number}: "
                        f"'mulligans to' implied {existing}, "
                        f"'begins the game' implied {authoritative}"
                    )
                current.mulligans_by_handle[handle] = authoritative
            continue

        m = patterns.turn.match(s)
        if m:
            handle = m.group("handle")
            handles.add(handle)
            # The printed per-player number — used only by the fallback gate
            # below, never stored. See the module docstring's "Turn units":
            # what gets stored is an ordinal count of `Turn` lines, Arena's
            # own units, not this raw MTGO number.
            turn_number = _ascii_int(m.group("n"))
            if turn_number is None:
                warnings.append(f"unrecognised turn number {m.group('n')!r}")
                continue
            if turn_number == 1 and (current is None or current.turn_count >= 2):
                # Fallback boundary only: the primary signal is the start
                # block above. Firing here means that block was never seen
                # (lost to a decode resync, or a truncated live read) — flag
                # it rather than let a second silent double-count happen.
                warnings.append(
                    f"game boundary inferred from 'Turn 1' with no preceding "
                    f"start block (game {len(games) + 1})"
                )
                current = _start_new_game(games)
                lost_connection.clear()
            if current is not None:
                # One `Turn` line = one player-turn (Arena's units): count
                # lines, don't track the printed N's own max.
                current.turn_count += 1
                current_turn = current.turn_count
            else:
                current_turn = None
            continue

        matched_card_event = False
        for category, pattern in patterns.card_events:
            m = pattern.match(s)
            if not m:
                continue
            matched_card_event = True
            handle = m.group("handle")
            handles.add(handle)
            if current is None:
                warnings.append(
                    f"card event before any game started: {category} "
                    f"{m.group('name')!r}"
                )
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

        m = patterns.concede.match(s)
        if m:
            handles.add(m.group("handle"))
            if current is not None:
                current.conceded_handle = m.group("handle")
                current.reason = "concede"
            continue

        m = patterns.loses_game.match(s)
        if m:
            handles.add(m.group("handle"))
            if current is not None:
                current.loser_handle = m.group("handle")
            continue

        m = patterns.inaction.match(s)
        if m:
            handles.add(m.group("handle"))
            if current is not None:
                current.loser_handle = m.group("handle")
                current.reason = "inaction"
            continue

        m = patterns.timeout.match(s)
        if m:
            handles.add(m.group("handle"))
            timed_out = m.group("handle")
            if current is not None:
                current.loser_handle = timed_out
                current.reason = "timeout"
            continue

        m = patterns.draw.match(s)
        if m:
            handles.update((m.group("a"), m.group("b")))
            if current is not None:
                current.draw = True
            continue

        m = patterns.wins_game.match(s)
        if m:
            handles.add(m.group("handle"))
            if current is not None:
                current.winner_handle = m.group("handle")
            continue

        m = patterns.wins_match.match(s)
        if m:
            handles.add(m.group("handle"))
            final_winner = m.group("handle")
            # falls through to the leads_match pattern below so the same line
            # also updates score_line — don't `continue` here.

        m = patterns.leads_match.match(s)
        if m:
            handles.add(m.group("handle"))
            a, b = _ascii_int(m.group("a")), _ascii_int(m.group("b"))
            if a is None or b is None:
                warnings.append(
                    f"unrecognised match score {m.group('a')!r}-{m.group('b')!r}"
                )
            else:
                score_line = (m.group("handle"), a, b)
            continue

        # Anything else is real MTGO text this parser has no use for yet
        # (see the module docstring's "deliberately not parsed" list) — not
        # a warning.

    for game in games:
        if game.contradicts():
            warnings.append(f"game {game.game_number}'s lines disagree about its result")

    return ParsedMatch(
        match_id=match_id, handles=handles, spectators=spectators, games=games,
        winner_handle=final_winner, timed_out_handle=timed_out,
        score_line=score_line, warnings=warnings,
    )


def last_game_decided(data: bytes) -> bool:
    """True when the last game in one game log's bytes names a winner, a
    loser or a draw (the module docstring's "Whether the last game is
    decided"). False for no game at all: empty bytes, garbage, a match still at
    its die roll.

    Never raises (non-negotiable #4): the watcher calls this from its poll
    loop on bytes it has not stored yet, half-copied ones included, and one
    file's bytes must not stop that loop. ``decode_strings`` and
    ``parse_strings`` are both written never to raise, but ``parse_strings``
    turns ``\\d+`` captures into ``int`` through guards: a count that is not
    ASCII digits (``\u0663``, which ``int()`` would read as 3) or is too long
    for ``int()`` (past 4,300 digits) is warned about and its line skipped
    rather than raised; whatever still escapes is logged and read as undecided.
    """
    try:
        games = parse_strings(decode_strings(data)).games
    except Exception as exc:
        log.warning("mtgo: could not tell whether the last game ended: %r", exc)
        return False
    if not games:
        return False
    last = games[-1]
    return last.winner_handle is not None or last.loser_handle is not None or last.draw
