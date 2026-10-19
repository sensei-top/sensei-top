"""Stage 2: project MTGO's ``raw_events`` rows into ``matches``, ``games``
and ``card_events``.

Scope, per the user's own decision (``.claude/handoffs/mtgo-implementation.md``):
through ``card_events`` only. **Never writes** ``turns``, ``turn_zones``,
``combat_*``, ``damage_events``, ``life_events``, ``game_decks``,
``deck_guids``, ``decks`` or ``rank_snapshot`` — MTGO's log has no life
totals or board state to put in them, and half-filling those tables would be
worse than leaving them empty (every ``self_*``/``opp_*`` column would be a
guess dressed as data).

Self/opponent and the seat convention
--------------------------------------
MTGO's log has no auth event and no seat concept at all — both are Arena-isms
this parser has nothing to read. Who is "us" comes from ``mtgo/config.py``'s
configured handle, checked against the two handles this specific match's log
actually mentions; no match, no guess (rule 4) — the match is skipped with a
warning, exactly like a missing handle skips *every* match.

``self_seat = 1`` / ``opponent_seat = 2`` is a fixed, made-up convention, not
observed data — but it has to exist anyway: ``v_opponent_cards`` (the view
that makes the matchups tab work at all) joins on
``ce.seat = m.opponent_seat``, so ``card_events.seat`` has to agree with
whatever ``matches.opponent_seat`` says. Documented here as exactly what it
is: an internal join key, chosen once and applied consistently, never
presented as something MTGO's log told us.

Picking one payload per match
------------------------------
``reader/mtgo.py`` stores a new ``raw_events`` row every time a game-log
file's size changes (MTGO flushes progressively during a match), so several
rows can share one ``source_file`` — each a longer prefix of the same
eventual file. The **longest** payload per ``source_file`` is the most
complete transcript, so that is the one decoded; the shorter, earlier
snapshots are real history (append-only, rule 2) but not projected.

``started_at`` / ``ended_at`` honesty
--------------------------------------
``started_at`` is the ``logged_at`` (file mtime) of the *first* ``raw_events``
row ever stored for this match's ``source_file`` — not the match's true start
time, which this log format cannot express. The live watcher's MTGO leg reads
the share once, at its own startup, and never polls it again (``live.py``) —
so for a match already under way when the process started, this is whatever
the file already held at that instant, not a value trailing the true first
flush by a bounded interval the way a polling leg's proxy would have been;
back-filled from a directory of already-finished matches (or from a hand-run
``sensei-top ingest-mtgo`` mid-session), it is roughly when the match
*ended* (the first and only time the tracker ever saw the file). Honest
under the name "first observed" either way — never claimed to be more than
that.

``ended_at`` is the last row's ``logged_at`` **only when the parser found a
"wins the match" line** (``parsed.winner_handle is not None``); otherwise
``NULL``. Writing a timestamp into a column named ``ended_at`` is a claim
that the match ended — an in-progress match (still in mulligans, or mid-game
with no winner recorded yet) must not make that claim, even though a row for
it already exists so the live tab has something to show.

Never discarded, even with zero games
---------------------------------------
Earlier versions of this projector discarded a parsed file entirely when it
had not reached a full game yet (``if not parsed.games: continue``) — but a
match still choosing mulligans, or one abandoned mid-file-write, has no
``Turn 1`` yet and *is* exactly the window this live feature exists to show.
``_write_match`` already tolerates empty ``games_rows``/``card_event_rows``
(``won = lost = 0``, ``result = 'incomplete'``), so nothing downstream needs
a nonzero game count to behave correctly.

⚠️ One consequence, accepted rather than special-cased: a ``.dat`` abandoned
while still tiny (a client crash between the opening die roll and the first
``joined the game`` line, so ``parsed.handles`` never resolves against the
configured handle) will re-emit the same "configured MTGO handle is not among
the players" warning on **every** rebuild, forever — the file never changes
again, so nothing about the input ever satisfies the check. This is
acceptable: it is real information (a match genuinely never got past that
point) and the file itself does not grow to invalidate it, so it does not
worsen over time.
"""

from __future__ import annotations

import base64
import binascii
import logging
import sqlite3

from sensei_top.projector.mtgo.decode import decode_strings
from sensei_top.projector.mtgo.parse import ParsedMatch, parse_strings

log = logging.getLogger(__name__)

SELF_SEAT = 1
OPPONENT_SEAT = 2

# A real file resyncs into well over a hundred strings (115, on the one real
# sample). Anything this much shorter is more likely a resync failure than a
# genuinely tiny match, and is worth a distinct warning rather than a silent
# "0 games" result.
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
    or not; this never brings them into Python at all. Window functions are
    already used elsewhere in this schema (migrations 004/016/033/035).
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
    """
    positive, negative = conn.execute(
        "SELECT MIN(CASE WHEN grp_id > 0 THEN grp_id END), "
        "       MIN(CASE WHEN grp_id < 0 THEN grp_id END) "
        "  FROM cards WHERE name = ?",
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
      which card it names) rather than picking one. Both are exact and
      case-sensitive ``substr`` comparisons, never ``LIKE``.

    Tried in order, stopping at the first hit: exact name, then token, then
    front-face prefix, then back-face suffix. A name ``_lookup`` finds on
    both a positive and a negative row stops the search too, unresolved: the
    exact name was found, only ambiguously, and a later rule must not turn it
    into another answer.
    ``cache`` is keyed
    by the MTGO name and remembers the final answer — ``None`` included — so
    a name repeated across many card events costs one query (and, when
    unresolved, one warning) for the whole projection run, not one per event.
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


def _write_match(
    conn: sqlite3.Connection,
    parsed: ParsedMatch,
    *,
    self_handle: str,
    opponent_handle: str,
    started_at: str | None,
    ended_at: str | None,
    grp_id_cache: dict[str, int | None],
    warner: _Warner,
    counts: dict[str, int],
) -> None:
    assert parsed.match_id is not None
    games_rows: list[tuple] = []
    card_event_rows: list[tuple] = []
    won = lost = 0

    for game in parsed.games:
        result = _game_result(game.winner_handle, self_handle, opponent_handle)
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

        result_reason = "concede" if game.conceded_handle is not None else None

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

    match_result = _game_result(parsed.winner_handle, self_handle, opponent_handle)

    # `format` is left out on purpose: MTGO's log never names one, so it is NULL.
    # best_of is 3: the MTGO constructed matches this tracker reads are best of
    # three (D2, the user's call); its log names no structure.
    conn.execute(
        """
        INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat,
                             opponent_user_id, opponent_name, started_at, ended_at,
                             result, games_won, games_lost, completed_reason, source,
                             best_of)
             VALUES (?, NULL, NULL, ?, ?, NULL, ?, ?, ?, ?, ?, ?, NULL, 'mtgo', 3)
        """,
        (
            parsed.match_id, SELF_SEAT, OPPONENT_SEAT, opponent_handle,
            started_at, ended_at, match_result, won, lost,
        ),
    )
    counts["matches"] += 1

    conn.executemany(
        """
        INSERT INTO games (match_id, game_number, on_play, result, result_reason,
                           turn_count, self_mulligans, opp_mulligans)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        games_rows,
    )
    counts["games"] += len(games_rows)

    conn.executemany(
        """
        INSERT INTO card_events (match_id, game_number, seq, turn_number,
                                 seat, grp_id, category, zone_src, zone_dest, mtgo_name)
             VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
        """,
        card_event_rows,
    )
    counts["card_events"] += len(card_event_rows)


def project_mtgo(conn: sqlite3.Connection, handle: str | None) -> dict[str, int]:
    """Project every MTGO match found in ``raw_events`` into ``matches``,
    ``games`` and ``card_events``. Runs inside the caller's own transaction
    (``projector/matches.py::project()``) — no ``BEGIN``/``COMMIT`` here.
    """
    counts = {"matches": 0, "games": 0, "card_events": 0, "warnings": 0}
    warner = _Warner()

    files = _select_latest_payload_per_file(conn)
    if handle is None:
        if files:
            warner.warn(
                f"no MTGO handle configured ($MTGO_HANDLE or [mtgo] handle in "
                f"config.toml) — skipping {len(files)} MTGO match file(s)"
            )
        counts["warnings"] = warner.count
        return counts

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
            # exchange decodes to only a handful of strings and is real, live
            # data (the window this feature exists for), not a resync
            # failure. It is still worth flagging — a genuine resync failure
            # looks identical from here — but the handle-resolution guard
            # below already refuses to write anything without two identified
            # players, so nothing is invented if this really was a failure.
            warner.warn(
                f"{source_file} decoded to only {len(strings)} string(s) — "
                "framing may not match expectations; not falling back to a "
                "heuristic scan (see projector/mtgo/decode.py)"
            )

        parsed = parse_strings(strings)
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

        # ended_at only when the parser actually found a match winner — see
        # the module docstring's "started_at / ended_at honesty" section.
        # Writing last_logged_at unconditionally would claim an in-progress
        # match had ended just because this rebuild happens to be its most
        # recent read.
        ended_at = last_logged_at if parsed.winner_handle is not None else None

        _write_match(
            conn, parsed,
            self_handle=handle, opponent_handle=opponent_handle,
            started_at=first_logged_at, ended_at=ended_at,
            grp_id_cache=grp_id_cache,
            warner=warner, counts=counts,
        )

    counts["warnings"] = warner.count
    return counts
