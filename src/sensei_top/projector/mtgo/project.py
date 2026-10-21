"""Stage 2: project MTGO's ``raw_events`` rows into ``matches``, ``games``
and ``card_events``.

Through ``card_events`` only, by the user's own decision. **Never writes**
``turns``, ``turn_zones``, ``combat_*``, ``damage_events``, ``life_events``,
``game_decks``, ``deck_guids``, ``decks`` or ``rank_snapshot`` — MTGO's log
has no life totals or board state to put in them, and half-filling those
tables would be worse than leaving them empty (every ``self_*``/``opp_*``
column would be a guess dressed as data). See docs/architecture.md, "What a
turn snapshot holds".

Self/opponent and the seat convention
--------------------------------------
MTGO's log has no auth event and no seat concept at all — both are Arena-isms
this parser has nothing to read. Who is "us" comes from ``mtgo/config.py``'s
configured handle, checked against the two handles this specific match's log
actually mentions; no match, no guess (rule 4) — the match is skipped with a
warning, exactly like a missing handle skips *every* match. The exception: a
match the configured handle only watched, with its ``has started watching.``
line and no player line, is skipped with a debug line, since nothing failed.

``self_seat = 1`` / ``opponent_seat = 2`` is a fixed, made-up convention, not
observed data — but it has to exist anyway: ``v_opponent_cards`` (the view
that makes the matchups tab work at all) joins on
``ce.seat = m.opponent_seat``, so ``card_events.seat`` has to agree with
whatever ``matches.opponent_seat`` says. It is an internal join key, chosen
once and applied consistently, never presented as something MTGO's log told
us.

Picking one payload per match
------------------------------
Every row ``reader/mtgo.py`` stores is the whole game-log file as it was then
(docs/architecture.md, "Storage"), so several rows can share one
``source_file``, each a longer prefix of the same eventual file. The
**longest** payload per ``source_file`` is the most complete transcript, so
that is the one decoded; the shorter, earlier snapshots are real history
(append-only, rule 2) but not projected.

``started_at`` / ``ended_at`` honesty
--------------------------------------
``started_at`` is the ``logged_at`` (file mtime) of the *first* ``raw_events``
row ever stored for this match's ``source_file`` — not the match's true start
time, which this log format cannot express. The watcher stores a game log
once a game ends (docs/architecture.md, "Live mode's two cadences"), so for
a match it watched from the start this is about when its first stored
game ended (game 1, unless a mirrored folder folded it into the next);
back-filled from a directory of already-finished matches (or by a hand-run
``sensei-top ingest-mtgo``), it is roughly when the match *ended*. Honest
under the name "first observed" either way — never claimed to be more than
that.

``ended_at`` is the last row's ``logged_at`` **only when the match has a
winner** (a "wins the match" line, or a "has run out of time and has lost the
match" line, which makes the other player the winner); otherwise ``NULL``.
Writing a timestamp into a column named ``ended_at`` is a claim that the
match ended — a match with no winner recorded yet (still in mulligans, or
mid-game) must not make that claim, even though a row for it exists.

Never discarded, even with zero games
---------------------------------------
A parsed file with no game yet (die rolls written, no ``joined the game``)
still gets its match row; one still choosing mulligans already has game 1,
with no turn.
``_match_rows`` already tolerates empty ``games_rows``/``card_event_rows``
(``won = lost = 0``, ``result = 'incomplete'``), so nothing downstream needs
a nonzero game count to behave correctly.

⚠️ One consequence, accepted rather than special-cased: a ``.dat`` abandoned
before its die-roll lines (only the match GUID written, so ``parsed.handles``
never holds the configured handle) re-emits the same "configured MTGO handle
is not among the players" warning on **every** rebuild, forever — the file
never changes again, so nothing about the input ever satisfies the check.
This is acceptable: it is real information (a match genuinely never got past
that point) and the file itself does not grow to invalidate it, so it does
not worsen over time.
"""

from __future__ import annotations

import base64
import binascii
import logging
import sqlite3
from dataclasses import dataclass, field

from sensei_top.projector.mtgo.decode import decode_strings
from sensei_top.projector.mtgo.parse import GameRecord, ParsedMatch, parse_strings

log = logging.getLogger(__name__)

SELF_SEAT = 1
OPPONENT_SEAT = 2

# A real file resyncs into well over a hundred strings (decode.py's module
# docstring has the one real sample's count). Anything this much shorter is
# more likely a resync failure than a genuinely tiny match, and is worth a
# distinct warning rather than a silent "0 games" result.
_MIN_PLAUSIBLE_STRINGS = 10


class _Warner:
    def __init__(self) -> None:
        self.count = 0

    def warn(self, message: str) -> None:
        self.count += 1
        log.warning("[mtgo] %s", message)


def _select_latest_payload_per_file(
    conn: sqlite3.Connection,
) -> list[tuple[str, str, str | None, str | None]]:
    """One ``(source_file, payload, first_logged_at, last_logged_at)`` per
    MTGO match: the longest payload seen for that file, plus the earliest and
    latest ``logged_at`` recorded for it (see the module docstring's
    "started_at / ended_at honesty" section for what those two become).

    A single windowed query rather than materialising every stored prefix in
    Python to compare ``len()`` — on a rebuild, the losing (shorter) prefixes
    for a long-lived match can be many times the winner's own bytes, decoded
    or not; this never brings them into Python at all.
    """
    rows = conn.execute(
        """
        SELECT source_file, payload, first_logged_at, last_logged_at FROM (
          SELECT source_file, payload,
                 MIN(logged_at) OVER (PARTITION BY source_file) AS first_logged_at,
                 MAX(logged_at) OVER (PARTITION BY source_file) AS last_logged_at,
                 ROW_NUMBER()   OVER (PARTITION BY source_file
                                      ORDER BY LENGTH(payload) DESC, id DESC) AS rn
            FROM raw_events WHERE source = 'mtgo'
        ) WHERE rn = 1 ORDER BY source_file
        """
    ).fetchall()
    return [
        (row["source_file"], row["payload"], row["first_logged_at"], row["last_logged_at"])
        for row in rows
    ]


def _lookup(conn: sqlite3.Connection, name: str) -> tuple[int | None, bool]:
    """``(grp_id, shared)`` for an exact name: an Arena (positive) id first,
    else the synthetic negative one ``cards --scryfall`` gives an MTGO-only
    card, with ``shared`` False.

    A name with both a positive and a negative row gives ``(None, True)``.
    What holds by construction is narrower than "two cards": a negative row
    sits beside a positive one only when two oracle cards answer to the name
    in Scryfall's export (``cards.py``, ``_write_synthetic_cards``). The two
    rows need not be those two cards. "Careful Study" is Odyssey's sorcery
    (the negative row) and a face of an Arena card (the positive one), but
    Arena's "Wheel of Fortune" row, which carries no oracle_id, and the
    negative row are both the classic card, while another card has a face of
    the same name. MTGO's transcript gives only the name, so nothing says
    which oracle card was played. Picking either would be a guess (rule 4);
    the caller warns and leaves it NULL.

    Among same-signed rows, the lowest id that has a ``card_legality`` row
    wins, else the lowest id. Arena keeps several rows of one card, and the
    lowest is often a reprint row Scryfall never matched: Swords to
    Plowshares is 59771 with no legality beside 77489 with seven, so taking
    the lowest left a revealed Swords unjudgeable in its format.
    """
    positive, negative = conn.execute(
        "WITH named AS ("
        "  SELECT grp_id, EXISTS (SELECT 1 FROM card_legality l"
        "                          WHERE l.grp_id = cards.grp_id) AS judged"
        "    FROM cards WHERE name = ?) "
        "SELECT COALESCE(MIN(CASE WHEN grp_id > 0 AND judged THEN grp_id END), "
        "                MIN(CASE WHEN grp_id > 0 THEN grp_id END)), "
        "       COALESCE(MIN(CASE WHEN grp_id < 0 AND judged THEN grp_id END), "
        "                MIN(CASE WHEN grp_id < 0 THEN grp_id END)) "
        "  FROM named",
        (name,),
    ).fetchone()
    if positive is not None and negative is not None:
        return None, True
    return (positive if positive is not None else negative), False


def _unresolved_shared_name(
    cache: dict[str, int | None], name: str, matched: str, warner: _Warner,
    face: str = "front",
) -> None:
    """Warn once and cache ``None`` for a name ``_lookup`` calls ambiguous.
    ``face`` says which face of ``matched`` the name was, when it differs."""
    via = "" if matched == name else f" ({face} face of {matched!r})"
    warner.warn(
        f"MTGO card name {name!r}{via} names both an Arena card and an "
        "MTGO-only card; left unresolved"
    )
    cache[name] = None
    return None


def _resolve_grp_id(
    conn: sqlite3.Connection,
    cache: dict[str, int | None],
    name: str,
    warner: _Warner,
) -> int | None:
    """Resolve one MTGO transcript name to a ``cards.grp_id``: Arena's own
    (positive) id when the card has one, else the synthetic negative id
    ``cards --scryfall`` gives an MTGO-only card (see ``_lookup``).

    An exact lookup alone leaves two kinds of real card unresolved, because
    MTGO's transcript spells them differently from Arena's ``cards.name``:

    - **Tokens.** MTGO writes ``"<Base> Token"`` — the fixture's own
      ``"Zombie Druid Token"`` (``uv run python scripts/mtgo_probe.py
      tests/fixtures/mtgo_match_session.log --force --lines 400``) — while
      Arena's DB carries the token as ``name='Zombie Druid'``,
      ``type_line='Token Creature — Zombie Druid'`` (grp_id 95829, measured).
      The ``type_line LIKE 'Token%'`` guard is required, not decorative: a
      token's base name can coincide with an unrelated *non-token* card's own
      name, and a plain name match would let that real card win a lookup
      that was never about it.
    - **Double-faced / adventure / split cards, by one face.** MTGO writes
      the face that was played — e.g. ``"Delver of Secrets"``, observed in
      real MTGO logs though not in this project's fixture — while Arena's DB
      has only the combined name (``"Delver of Secrets // Insectile
      Aberration"``). The back-face spelling is observed too: MTGO names a
      transformed or back-played face by that face. The fixture's own
      ``"Player2000 casts @[Dread Whispers@:…:@]"`` (probe line 61) is the
      adventure half of ``"Mosswood Dreadknight // Dread Whispers"``, and a
      real MTGO history carried ``"Sea Gate, Reborn"`` and ``"Tamiyo,
      Seasoned Scholar"``. So there are two rules: a front-face *prefix*
      match, then a back-face *suffix* match (the name equals the part after
      the last ``" // "``), each taken only when it identifies exactly one
      combined name. More than one match is left unresolved with a warning
      naming them (rule 4: an ambiguous face is not resolved by guessing
      which card it names) rather than picking one.

    Tried in order, stopping at the first hit: exact name, then token, then
    front-face prefix, then back-face suffix. A name ``_lookup`` finds on
    both a positive and a negative row stops the search too, unresolved: the
    exact name was found, only ambiguously, and a later rule must not turn it
    into another answer. ``cache`` is keyed by the MTGO name and remembers
    the final answer — ``None`` included — so a name repeated across many
    card events costs one query (and, when unresolved, one warning) for the
    whole projection run, not one per event.
    """
    if name in cache:
        return cache[name]

    grp_id, shared = _lookup(conn, name)
    if shared:
        return _unresolved_shared_name(cache, name, name, warner)

    if grp_id is None and name.endswith(" Token"):
        base = name[: -len(" Token")]
        row = conn.execute(
            "SELECT MIN(grp_id) FROM cards WHERE name = ? AND type_line LIKE 'Token%'",
            (base,),
        ).fetchone()
        grp_id = row[0] if row is not None else None

    # substr(...) = ..., not LIKE: LIKE is case-insensitive and treats '%'/'_'
    # as wildcards, and each of these must be an exact, case-sensitive test.
    for face, condition in (
        ("front", "substr(name, 1, length(?) + 4) = ? || ' // '"),
        ("back", "substr(name, -(length(?) + 4)) = ' // ' || ?"),
    ):
        if grp_id is not None:
            break
        candidates = sorted(
            row[0]
            for row in conn.execute(
                f"SELECT DISTINCT name FROM cards WHERE {condition}", (name, name)
            )
        )
        if len(candidates) == 1:
            grp_id, shared = _lookup(conn, candidates[0])
            if shared:
                return _unresolved_shared_name(cache, name, candidates[0], warner, face)
        elif len(candidates) > 1:
            warner.warn(
                f"MTGO card name not found in cards.name: {name!r} "
                f"({face} face of {len(candidates)} cards: "
                + ", ".join(repr(c) for c in candidates) + ")"
            )
            cache[name] = None
            return None

    if grp_id is None:
        warner.warn(f"MTGO card name not found in cards.name: {name!r}")

    cache[name] = grp_id
    return grp_id


def _game_result(winner_handle: str | None, self_handle: str, opponent_handle: str) -> str:
    if winner_handle == self_handle:
        return "win"
    if winner_handle == opponent_handle:
        return "loss"
    return "incomplete"


def _game_outcome(game: GameRecord, self_handle: str, opponent_handle: str) -> str:
    """A game's result: its winner, else its loser's opponent wins, else a
    draw, else ``incomplete``. Lines that disagree (the same handle won and
    lost; a draw beside a winner) are ``incomplete``, never a pick (rule 4)."""
    if game.contradicts():
        return "incomplete"
    if game.winner_handle is not None:
        return _game_result(game.winner_handle, self_handle, opponent_handle)
    if game.loser_handle is not None:
        # The other handle of the two, whichever lost: a loser who is neither
        # is not this match's player, so nothing is said.
        if game.loser_handle == self_handle:
            return "loss"
        if game.loser_handle == opponent_handle:
            return "win"
        return "incomplete"
    if game.draw:
        return "draw"
    return "incomplete"


def _match_winner(
    parsed: ParsedMatch, self_handle: str, opponent_handle: str
) -> str | None:
    """The ``wins the match`` handle, else the other side of the handle whose
    clock ran out (a time-out loses the match, and not every log then goes on
    to say who won it)."""
    if parsed.winner_handle is not None:
        return parsed.winner_handle
    if parsed.timed_out_handle == self_handle:
        return opponent_handle
    if parsed.timed_out_handle == opponent_handle:
        return self_handle
    return None


# The reason column in Arena's names, so the match report and the sideboard card
# read an MTGO game unchanged. "ResultReason_Inaction" is MTGO's own: Arena
# has no such ending, and the report has no wording for it.
_RESULT_REASONS = {
    "concede": "ResultReason_Concede",
    "timeout": "ResultReason_Timeout",
    "inaction": "ResultReason_Inaction",
}


@dataclass
class MtgoRows:
    """Every row ``write_mtgo`` inserts, built by ``read_mtgo`` before the
    rebuild takes the write lock (``projector/matches.py::project()``)."""

    matches: list[tuple] = field(default_factory=list)
    games: list[tuple] = field(default_factory=list)
    card_events: list[tuple] = field(default_factory=list)
    warnings: int = 0


def _match_rows(
    conn: sqlite3.Connection,
    parsed: ParsedMatch,
    *,
    self_handle: str,
    opponent_handle: str,
    started_at: str | None,
    ended_at: str | None,
    grp_id_cache: dict[str, int | None],
    warner: _Warner,
    rows: MtgoRows,
) -> None:
    assert parsed.match_id is not None
    games_rows = rows.games
    card_event_rows = rows.card_events
    won = lost = 0

    for game in parsed.games:
        result = _game_outcome(game, self_handle, opponent_handle)
        if result == "win":
            won += 1
        elif result == "loss":
            lost += 1

        on_play: int | None
        if game.on_play_handle == self_handle:
            on_play = 1
        elif game.on_play_handle == opponent_handle:
            on_play = 0
        else:
            on_play = None

        result_reason = _RESULT_REASONS.get(game.reason) if game.reason else None

        games_rows.append(
            (
                parsed.match_id, game.game_number, on_play, result, result_reason,
                game.turn_count or None,
                game.mulligans_by_handle.get(self_handle),
                game.mulligans_by_handle.get(opponent_handle),
            )
        )

        for seq, event in enumerate(game.card_events):
            if event.handle == self_handle:
                seat = SELF_SEAT
            elif event.handle == opponent_handle:
                seat = OPPONENT_SEAT
            else:
                seat = None
                warner.warn(
                    f"a card event's player is neither of the match's two in "
                    f"match {parsed.match_id}, game {game.game_number}"
                )
            grp_id = _resolve_grp_id(conn, grp_id_cache, event.name, warner)
            # The transcript's name only where no card stands for it: what
            # lets infer_formats set an unresolved token or game marker aside
            # (migrations/060_card_event_mtgo_name.sql).
            card_event_rows.append(
                (
                    parsed.match_id, game.game_number, seq, event.turn_number,
                    seat, grp_id, event.category,
                    event.name if grp_id is None else None,
                )
            )

    match_winner = _match_winner(parsed, self_handle, opponent_handle)
    match_result = _game_result(match_winner, self_handle, opponent_handle)

    # `format` is left out on purpose: MTGO's log never names one, so it is NULL.
    # best_of is 3: the MTGO constructed matches this tracker reads are best of
    # three (the user's call); its log names no structure.
    rows.matches.append(
        (
            parsed.match_id, SELF_SEAT, OPPONENT_SEAT, opponent_handle,
            started_at, ended_at, match_result, won, lost,
        )
    )


def write_mtgo(conn: sqlite3.Connection, rows: MtgoRows) -> dict[str, int]:
    """Insert what ``read_mtgo`` built. Runs inside the caller's own
    transaction (``projector/matches.py::project()``) — no
    ``BEGIN``/``COMMIT`` here — and reads nothing, so the write lock is held
    for the inserts alone."""
    conn.executemany(
        """
        INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat,
                             opponent_user_id, opponent_name, started_at, ended_at,
                             result, games_won, games_lost, completed_reason, source,
                             best_of)
             VALUES (?, NULL, NULL, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, 'mtgo', 3)
        """,
        rows.matches,
    )
    conn.executemany(
        """
        INSERT INTO games (match_id, game_number, on_play, result, result_reason,
                           turn_count, self_mulligans, opp_mulligans)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows.games,
    )
    conn.executemany(
        """
        INSERT INTO card_events (match_id, game_number, seq, turn_number,
                                 seat, grp_id, category, zone_src, zone_dest, mtgo_name)
             VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
        """,
        rows.card_events,
    )
    return {
        "matches": len(rows.matches),
        "games": len(rows.games),
        "card_events": len(rows.card_events),
        "warnings": rows.warnings,
    }


def project_mtgo(conn: sqlite3.Connection, handle: str | None) -> dict[str, int]:
    """Project every MTGO match found in ``raw_events`` into ``matches``,
    ``games`` and ``card_events``: ``read_mtgo`` then ``write_mtgo``. Runs
    inside the caller's own transaction — no ``BEGIN``/``COMMIT`` here.
    ``project()`` calls the two halves itself, the read before its
    transaction opens.
    """
    return write_mtgo(conn, read_mtgo(conn, handle))


def read_mtgo(conn: sqlite3.Connection, handle: str | None) -> MtgoRows:
    """Read, decode and parse every MTGO match in ``raw_events`` into the
    rows ``write_mtgo`` inserts. Writes nothing: ``project()`` runs it
    before ``BEGIN``, because decoding every stored game log takes seconds,
    and inside the transaction those seconds held the write lock the live
    watcher's ingest thread waits on (``docs/architecture.md``, "Live mode's
    two cadences").
    """
    rows = MtgoRows()
    warner = _Warner()

    files = _select_latest_payload_per_file(conn)
    if handle is None:
        if files:
            warner.warn(
                f"no MTGO handle configured ($MTGO_HANDLE or [mtgo] handle in "
                f"config.toml) — skipping {len(files)} MTGO match file(s)"
            )
        rows.warnings = warner.count
        return rows

    grp_id_cache: dict[str, int | None] = {}
    for source_file, payload_b64, first_logged_at, last_logged_at in files:
        try:
            data = base64.b64decode(payload_b64)
        except (ValueError, binascii.Error):
            warner.warn(f"could not base64-decode payload for {source_file}")
            continue

        strings = decode_strings(data)
        if len(strings) < _MIN_PLAUSIBLE_STRINGS:
            # A warning, not a skip: a match still in its opening die-roll
            # exchange decodes to only a handful of strings and is real data,
            # not a resync failure. It is still worth flagging — a genuine
            # resync failure looks identical from here — but the
            # handle-resolution guard below already refuses to write anything
            # without two identified players, so nothing is invented if this
            # really was a failure.
            warner.warn(
                f"{source_file} decoded to only {len(strings)} string(s) — "
                "framing may not match expectations; not falling back to a "
                "heuristic scan (see projector/mtgo/decode.py)"
            )

        parsed = parse_strings(strings)
        # A match the user only watched: their handle "has started watching"
        # and is no player. The parser warns once per card line for a file
        # with no start block, so this comes before that loop and before the
        # handle guards. A debug line, not a warning: watching is no fault,
        # and a warning would recur on every rebuild. Like the guards below,
        # it never names the handle.
        if handle in parsed.spectators and handle not in parsed.handles:
            log.debug(
                "%s: the configured MTGO handle only watched match %s; skipping it",
                source_file,
                parsed.match_id,
            )
            continue
        for w in parsed.warnings:
            warner.warn(f"{source_file}: {w}")

        if parsed.match_id is None:
            warner.warn(f"{source_file}: no match GUID found in decoded strings")
            continue

        # Counts, never the handles: this line reaches the log, and the log
        # the diagnostics zip a public bug report attaches.
        others = parsed.handles - {handle}
        if handle not in parsed.handles:
            warner.warn(
                f"{source_file}: the configured MTGO handle is not among the "
                f"{len(parsed.handles)} player(s) of match {parsed.match_id}"
            )
            continue
        if len(others) != 1:
            warner.warn(
                f"{source_file}: the configured MTGO handle has {len(others)} "
                f"opponents rather than one in match {parsed.match_id}"
            )
            continue
        opponent_handle = next(iter(others))

        # ended_at only with a match winner (module docstring's "started_at /
        # ended_at honesty").
        ended_at = (
            last_logged_at
            if _match_winner(parsed, handle, opponent_handle) is not None
            else None
        )

        _match_rows(
            conn, parsed,
            self_handle=handle, opponent_handle=opponent_handle,
            started_at=first_logged_at, ended_at=ended_at,
            grp_id_cache=grp_id_cache,
            warner=warner, rows=rows,
        )

    rows.warnings = warner.count
    return rows
