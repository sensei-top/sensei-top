"""Tournament results from the TopDeck.gg API — a second source for
the corpus ``metagame/source.py`` already builds, added because a live
comparison of one August's Standard corpus found the fbettega cache holding
almost no large-paper Standard evidence: MTGO's own Standard events are all
leagues (Tier C, presence-only — a league dump has no losses in it at all),
so real Standard matchup data comes down to the handful of paper events Melee
happens to publish. TopDeck.gg is where Standard RCQs and Regional
Championships are actually run and scored — real tabletop swiss events, the
shape the tier system ranks highest at tournament size.

This module does not reimplement the corpus pipeline. It normalises a
TopDeck API response into the same ``CacheItem`` shape
``metagame/source.py``'s :func:`~sensei_top.metagame.source.parse_event`
already parses, then hands off to that function unchanged — including its
own call to :func:`~sensei_top.metagame.tiers.classify_tier`. A TopDeck event
is tabletop, so it earns Tier A or D on the exact same size test (64 or more
real ``Standings`` rows for A, fewer for D) as every Melee-sourced event;
nothing here trusts an event for where it came from.

Privacy, automatically. TopDeck standings and round tables carry a player's
real display name and account id. Both are used here purely as an in-memory
join key — mapped into ``CacheItem["Decks"][i]["Player"]``, the exact field
:func:`~sensei_top.metagame.source.parse_event` already resolves to a
per-event ordinal and discards before anything reaches ``store_events``, per
that module's own docstring and AGENTS.md's privacy rule. Nothing in this
module writes a name or id anywhere else in the normalised payload, so the
existing pipeline's privacy guarantee is inherited rather than re-implemented.

Credential: an opt-in, unmetered API key (AGENTS.md's "standard for the free
downloads that remain", not the metered-call rule) resolved by
``metagame/config.py``, a sibling to ``llm/config.py`` rather than an
extension of it. With no key configured, :func:`refresh_topdeck` is a no-op.
Attribution: TopDeck's terms require a visible credit and link back to
TopDeck.gg wherever this data is shown; see ``FieldView.tsx``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sensei_top.metagame.config import load as load_config
from sensei_top.metagame.holds import (
    TIME_FORMAT,
    TOPDECK,
    Gate,
    apply_outcome,
    gate,
    parse_retry_after,
    read_hold,
)
from sensei_top.metagame.source import (
    DEFAULT_WINDOW_DAYS,
    FETCH_FORMATS,
    Answer,
    AnswerKind,
    RefreshResult,
    TournamentFile,
    already_fetched,
    answer_kind,
    answer_reason,
    has_lists,
    parse_event,
    record_read,
    store_events,
)

log = logging.getLogger(__name__)

# api.topdeck.gg never resolved (DNS), so no TopDeck event was stored until
# this base was corrected to the host that answers.
API_BASE = "https://topdeck.gg/api/v2"
TIMEOUT = 30.0
GAME = "Magic: The Gathering"

MAX_AGE_SECONDS = 24 * 3600
# Between one format's query and the next.
FORMAT_SPACING_S = 15.0

# Organisers label commander nights, drafts and prereleases "Standard" too.
# Leading boundary only: "Pre Release", "Prerelease" and the misspelt
# "PreRealese" must all match.
_NOT_CONSTRUCTED_RE = re.compile(
    r"(?<![a-z])(commander|edh|draft|sealed|cube|jumpstart|pre.?r?e?a?l)", re.IGNORECASE
)

# One request line per tournament line in a decklist export: "4 Lightning
# Bolt" or "4x Lightning Bolt". Fallback path only, for a standings row whose
# deckObj carries no recognisable Mainboard/Sideboard structure — see
# _parse_decklist_text below.
_DECKLIST_LINE_RE = re.compile(r"^\s*(\d+)x?\s+(.+?)\s*$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _post_json(path: str, body: dict[str, Any], *, api_key: str, timeout: float = TIMEOUT) -> Any:
    """The only networked function. One POST, one response, no query string
    on the URL — the request body carries every filter."""
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "User-Agent": "sensei-top/0.1",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def list_tournaments(
    *, api_key: str, start: date, end: date, format: str, game: str = GAME
) -> list[dict[str, Any]]:
    """Every matching tournament in the window, each already carrying its own
    standings and round-by-round tables — TopDeck's query mode returns full
    data per tournament in one call, so there is no separate per-TID fetch."""
    start_ts = int(datetime.combine(start, datetime.min.time(), tzinfo=UTC).timestamp())
    end_ts = int(datetime.combine(end, datetime.min.time(), tzinfo=UTC).timestamp()) + 86400
    body = {
        "game": game,
        "format": format,
        "start": start_ts,
        "end": end_ts,
        "columns": ["name", "decklist", "deckObj", "wins", "draws", "losses"],
        "rounds": True,
    }
    data = _post_json("/tournaments", body, api_key=api_key)
    return list(data) if isinstance(data, list) else []


def _deck_object_entries(deck_obj: Any, key: str) -> list[dict[str, Any]] | None:
    """``deckObj[key]`` (``"Mainboard"`` or ``"Sideboard"``), normalised to
    the ``[{"CardName": ..., "Count": ...}]`` shape ``_card_entries`` already
    accepts. TopDeck's own docs show only a Commander example
    (``{"Commanders": {}, "Mainboard": {}}``); the exact section shape for a
    Standard deck was not verified against a real response, so this reads
    tolerantly and returns ``None`` — not an empty list, so the caller can
    fall back to the decklist text — whenever the section is missing or in a
    shape neither branch below recognises. Never guessed at (rule 4)."""
    if not isinstance(deck_obj, dict):
        return None
    section = deck_obj.get(key)
    if isinstance(section, dict):
        return [{"CardName": name, "Count": count} for name, count in section.items()]
    if isinstance(section, list):
        return [item for item in section if isinstance(item, dict)]
    return None


def _parse_decklist_text(text: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fallback for a standings row whose ``deckObj`` didn't parse: TopDeck's
    ``decklist`` free-text field, in the common "N Card Name" per line export
    shape, with an optional "Sideboard" heading splitting the two halves.
    Any line that doesn't match is simply skipped, same as a malformed
    ``Mainboard``/``Sideboard`` entry elsewhere in this corpus."""
    if not isinstance(text, str) or not text.strip():
        return [], []
    mainboard: list[dict[str, Any]] = []
    sideboard: list[dict[str, Any]] = []
    in_sideboard = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().lstrip("~ ").startswith("sideboard"):
            in_sideboard = True
            continue
        if stripped.lower().lstrip("~ ").startswith("commanders"):
            continue
        match = _DECKLIST_LINE_RE.match(stripped)
        if not match:
            continue
        count, name = match.groups()
        entry = {"CardName": name, "Count": int(count)}
        (sideboard if in_sideboard else mainboard).append(entry)
    return mainboard, sideboard


def _round_matches(rounds: Any) -> list[dict[str, Any]]:
    """TopDeck's ``rounds[].tables[]`` (``players``, ``winner``,
    ``winner_games``, ``loser_games``, ``status``), normalised into the
    ``CacheItem["Rounds"]`` shape ``parse_event`` already reads —
    ``{"RoundName": ..., "Matches": [{"Player1", "Player2", "Result"}]}``,
    with ``Result`` built as a "W-L-D" string so ``_parse_record`` (already
    reused, unchanged) parses it straight back into the same numbers.

    Only a two-player, completed table becomes a match: a team-format table,
    a bye, or one still in progress carries no honest deck-to-deck result to
    record, so it is dropped rather than guessed at.
    """
    normalized: list[dict[str, Any]] = []
    for rnd in rounds or []:
        if not isinstance(rnd, dict):
            continue
        matches: list[dict[str, Any]] = []
        for table in rnd.get("tables") or []:
            if not isinstance(table, dict) or table.get("status") != "Completed":
                continue
            players = table.get("players") or []
            if len(players) != 2:
                continue
            name_a = players[0].get("name") if isinstance(players[0], dict) else None
            name_b = players[1].get("name") if isinstance(players[1], dict) else None
            if not name_a or not name_b:
                continue
            winner = table.get("winner")
            winner_games = table.get("winner_games")
            loser_games = table.get("loser_games")
            if not isinstance(winner_games, int) or not isinstance(loser_games, int):
                continue
            if winner == name_a:
                wins_a, wins_b = winner_games, loser_games
            elif winner == name_b:
                wins_a, wins_b = loser_games, winner_games
            else:
                # No winner named (a draw, or an unresolved result) — nothing
                # here tells us which side got which count.
                continue
            matches.append(
                {"Player1": name_a, "Player2": name_b, "Result": f"{wins_a}-{wins_b}-0"}
            )
        normalized.append({"RoundName": str(rnd.get("round") or ""), "Matches": matches})
    return normalized


def _normalize(tournament: dict[str, Any]) -> dict[str, Any]:
    """One TopDeck tournament object -> one ``CacheItem``-shaped dict, the
    same shape ``fbettega/MTG_decklistcache`` ships and ``parse_event``
    already parses. Deliberately produces exactly the fields that module
    reads and nothing else."""
    standings = tournament.get("standings") or []
    decks: list[dict[str, Any]] = []
    standings_rows: list[dict[str, Any]] = []
    for row in standings:
        if not isinstance(row, dict):
            continue
        player = row.get("name")
        if not isinstance(player, str) or not player:
            continue
        mainboard = _deck_object_entries(row.get("deckObj"), "Mainboard")
        sideboard = _deck_object_entries(row.get("deckObj"), "Sideboard")
        if mainboard is None:
            mainboard, sideboard_from_text = _parse_decklist_text(row.get("decklist"))
            sideboard = sideboard if sideboard is not None else sideboard_from_text
        decks.append(
            {
                "Player": player,
                "Result": None,
                "Mainboard": mainboard,
                "Sideboard": sideboard or [],
            }
        )
        wins = row.get("wins")
        losses = row.get("losses")
        draws = row.get("draws")
        if isinstance(wins, int) and isinstance(losses, int):
            standings_rows.append({
                "Player": player,
                "Wins": wins,
                "Losses": losses,
                "Draws": draws if isinstance(draws, int) else 0,
            })

    tid = tournament.get("TID")
    return {
        "Tournament": {
            "Name": tournament.get("tournamentName"),
            "Date": _iso_date(tournament.get("startDate")),
            "Formats": tournament.get("format"),
            "Uri": f"https://topdeck.gg/event/{tid}" if tid else None,
        },
        "Decks": decks,
        "Standings": standings_rows,
        "Rounds": _round_matches(tournament.get("rounds")),
    }


def _iso_date(unix_seconds: Any) -> str | None:
    if not isinstance(unix_seconds, int | float):
        return None
    try:
        return datetime.fromtimestamp(unix_seconds, tz=UTC).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return None


def _blob_sha(payload: dict[str, Any]) -> str:
    """A completed tournament's own data never changes, so hashing the fetched
    object is what makes a refresh incremental — the same role
    ``TournamentFile.blob_sha`` already plays for a fbettega file, just
    computed here instead of read from a git tree."""
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _purge_not_constructed(conn) -> None:
    """Delete already-stored TopDeck events whose name matches the rule, with
    every child row, in one transaction."""
    rows = conn.execute(
        "SELECT event_id, name FROM meta_event WHERE event_id LIKE 'Tournaments/Topdeck/%'"
    ).fetchall()
    doomed = [r["event_id"] for r in rows if _NOT_CONSTRUCTED_RE.search(r["name"] or "")]
    if not doomed:
        return
    log.warning("topdeck: purging %d stored non-constructed events", len(doomed))
    conn.execute("BEGIN")
    try:
        for event_id in doomed:
            conn.execute(
                "UPDATE meta_event SET duplicate_of = NULL WHERE duplicate_of = ?", (event_id,)
            )
            for table in ("meta_deck_archetype", "meta_round_match", "meta_deck"):
                conn.execute(f"DELETE FROM {table} WHERE event_id = ?", (event_id,))
            conn.execute("DELETE FROM meta_event WHERE event_id = ?", (event_id,))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def _body_retry_seconds(exc: urllib.error.HTTPError) -> float | None:
    """The ``retryAfterSeconds`` of a 429's JSON body (TopDeck's "Rate
    Limited" response), or None when the body is missing, is not a JSON
    object or names no usable number. Never guessed at (rule 4)."""
    try:
        data = json.loads(exc.read().decode("utf-8"))
    except (OSError, ValueError, AttributeError):
        return None
    if not isinstance(data, dict) or "retryAfterSeconds" not in data:
        return None
    value = data["retryAfterSeconds"]
    if (isinstance(value, bool) or not isinstance(value, int | float)
            or not math.isfinite(value)):
        log.warning("unusable retryAfterSeconds %r, treated as absent", value)
        return None
    return float(value)


def _ended_by(
    exc: urllib.error.HTTPError, *, fmt: str, first: bool, at: datetime
) -> Answer | None:
    """The Answer a refusal (401, 403, 451) or a 429 makes of ``exc``; None
    for any other status, which is "no answer for" the format."""
    kind = answer_kind(exc.code)
    if kind not in (AnswerKind.REFUSED, AnswerKind.RATE):
        return None
    header = exc.headers.get("Retry-After") if exc.headers is not None else None
    return Answer(
        kind=kind, reason=answer_reason(exc), at=at, http_status=exc.code, place=fmt,
        retry_after=parse_retry_after(header, at=at),
        retry_after_s=_body_retry_seconds(exc) if kind == AnswerKind.RATE else None,
        first_request=first,
    )


def _stamp(t: datetime) -> str:
    return t.astimezone(UTC).strftime(TIME_FORMAT)


def _stored_age(conn, at: datetime) -> float | None:
    """Seconds from the last completed run's stamp to ``at`` (the run's
    clock), or None with no usable stamp."""
    row = conn.execute(
        "SELECT fetched_at FROM meta_fetch_source WHERE source = 'topdeck'"
    ).fetchone()
    if row is None or not row["fetched_at"]:
        return None
    try:
        fetched = datetime.strptime(row["fetched_at"], TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (at - fetched).total_seconds()


def refresh_topdeck(
    conn,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_age_seconds: float = MAX_AGE_SECONDS,
    force: bool = False,
    formats: Sequence[str] = FETCH_FORMATS,
    fetch: Callable[..., list[dict[str, Any]]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _utc_now,
    by_hand: bool = False,
) -> RefreshResult:
    """Update the corpus from TopDeck.gg, for each of ``formats`` (one query
    each, one key, ``FORMAT_SPACING_S`` apart), through the source's hold
    (plan 14, S3 and S5). Never raises on a failed request.

    No credential configured is its own status, checked first; a missing
    opt-in key is not an error. Then the gate: ``held`` and ``fresh`` make no
    request. ``now`` is the run's clock, read at the start, when an answer
    arrives and at the end; ``by_hand`` is only read by the gate. ``fetch``
    is ``list_tournaments`` unless a test passes another.

    A status that is not a refusal (401, 403, 451) or a 429 is "no answer
    for" that format and the run goes on. A refusal or a 429 ends the run:
    the formats after it are ``unfetched``, the run is ``failed`` with the
    answer, unstamped, and the hold moves. Every format unanswered is a
    ``failed`` run with a generic answer and the hold unchanged. Otherwise
    the run completed, even if some formats went unanswered (``error`` lists
    them): it is stamped and lifts any hold. Whatever was parsed is stored
    either way.
    """
    config = load_config()
    if config is None:
        return RefreshResult(status="not_configured")

    started = now()
    before = read_hold(conn, TOPDECK)
    passage = gate(before, now=started, by_hand=by_hand)
    age = _stored_age(conn, started)
    if passage == Gate.HELD:
        return RefreshResult(
            status="held", age_seconds=age, hold_before=before, hold_after=before,
            by_hand=by_hand,
        )
    if (passage == Gate.FRESHNESS and not force and age is not None
            and age < max_age_seconds):
        return RefreshResult(
            status="fresh", age_seconds=age, hold_before=before, hold_after=before,
            by_hand=by_hand,
        )

    query = fetch if fetch is not None else list_tournaments
    end = started.date()
    start = end - timedelta(days=window_days)

    tournaments: list[tuple[str, dict[str, Any]]] = []
    answered: list[str] = []
    unanswered: list[str] = []
    reasons: list[str] = []
    answer: Answer | None = None
    unfetched: tuple[str, ...] = ()
    for index, fmt in enumerate(formats):
        if index:
            sleep(FORMAT_SPACING_S)
        try:
            found = query(api_key=config.api_key, start=start, end=end, format=fmt)
        except urllib.error.HTTPError as exc:
            ending = _ended_by(exc, fmt=fmt, first=index == 0, at=now())
            if ending is not None:
                answer = ending
                unfetched = tuple(formats[index + 1:])
                log.warning("topdeck answered %s for %s; ending the run", ending.reason, fmt)
                break
            reason = answer_reason(exc)
            log.warning("topdeck refresh failed for %s: %s", fmt, reason)
            unanswered.append(fmt)
            reasons.append(reason)
            continue
        except (urllib.error.URLError, TimeoutError, ValueError, OSError,
                json.JSONDecodeError) as exc:
            reason = answer_reason(exc)
            log.warning("topdeck refresh failed for %s: %s", fmt, reason)
            unanswered.append(fmt)
            reasons.append(reason)
            continue
        answered.append(fmt)
        tournaments.extend((fmt, t) for t in found)
    if answer is None and unanswered and not answered:
        log.warning("topdeck refresh failed, keeping the cached copy")
        answer = Answer(kind=AnswerKind.GENERIC, reason=reasons[0], at=now())

    known = already_fetched(conn)
    events = []
    reads: list[tuple[str, str]] = []
    skipped = 0
    seen: set[str] = set()
    for fmt, tournament in tournaments:
        tid = tournament.get("TID")
        if not tid:
            skipped += 1
            continue
        if tid in seen:
            continue
        seen.add(tid)
        if _NOT_CONSTRUCTED_RE.search(str(tournament.get("tournamentName") or "")):
            log.warning("topdeck event skipped: name matches the non-constructed rule")
            skipped += 1
            continue
        if not tournament.get("format"):
            # The query filtered on this format, so an object that omits it
            # still belongs to it.
            tournament = {**tournament, "format": fmt}
        raw = _normalize(tournament)
        blob_sha = _blob_sha(raw)
        # Namespaced like fbettega's own "Tournaments/<source>/..." layout —
        # not just for uniqueness (already-fetched dedup keys on the full
        # path) but because parse_event derives ParsedEvent.source from
        # path.split("/", 2)[1], so this shape is what makes a TopDeck event
        # report source="Topdeck" rather than the TID filename itself.
        path = f"Tournaments/Topdeck/{tid}.json"
        parsed = parse_event(raw, TournamentFile(path=path, blob_sha=blob_sha), formats)
        if parsed is None:
            skipped += 1
            continue
        if known.get(path) == blob_sha:
            # An identical copy is not stored again, but it is a read.
            reads.append((path, "lists" if has_lists(parsed) else "empty"))
            continue
        events.append(parsed)

    # Every read in this run is stamped with its start, as mtgo.com's are.
    read_at = _stamp(started)
    stored = store_events(conn, events, now=read_at)
    skipped += len(events) - stored
    _purge_not_constructed(conn)
    ended = now()
    conn.execute("BEGIN")
    try:
        for event_id, outcome in reads:
            record_read(conn, event_id, outcome=outcome, now=read_at)
        after = apply_outcome(
            conn, TOPDECK, before=before, answer=answer, page_read=False,
            completed=answer is None, now=answer.at if answer is not None else ended,
        )
        if answer is None:
            conn.execute(
                """
                INSERT INTO meta_fetch_source
                     (source, ref, fetched_at, window_days, events, skipped)
                     VALUES ('topdeck', ?, ?, ?, ?, ?)
                ON CONFLICT (source) DO UPDATE SET
                     ref = excluded.ref, fetched_at = excluded.fetched_at,
                     window_days = excluded.window_days, events = excluded.events,
                     skipped = excluded.skipped
                """,
                (API_BASE, _stamp(ended), window_days, stored, skipped),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = RefreshResult(
        status="updated", events=stored, skipped=skipped,
        age_seconds=_stored_age(conn, ended), hold_before=before, hold_after=after,
        by_hand=by_hand, answered=tuple(answered), unfetched=unfetched,
        unanswered=tuple(unanswered),
        error=", ".join(unanswered) if unanswered else None,
    )
    if answer is None:
        return result
    return replace(result, status="failed", error=answer.reason, answer=answer)
