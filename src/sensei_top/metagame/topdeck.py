"""Standard tournament results from the TopDeck.gg API — a second source for
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
import re
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sensei_top.metagame.config import load as load_config
from sensei_top.metagame.source import (
    DEFAULT_WINDOW_DAYS,
    RefreshResult,
    TournamentFile,
    already_fetched,
    parse_event,
    store_events,
)

log = logging.getLogger(__name__)

# api.topdeck.gg never resolved (DNS), so no TopDeck event was stored until
# this base was corrected to the host that answers.
API_BASE = "https://topdeck.gg/api/v2"
TIMEOUT = 30.0
GAME = "Magic: The Gathering"
FORMAT = "Standard"

MAX_AGE_SECONDS = 24 * 3600

# One request line per tournament line in a decklist export: "4 Lightning
# Bolt" or "4x Lightning Bolt". Fallback path only, for a standings row whose
# deckObj carries no recognisable Mainboard/Sideboard structure — see
# _parse_decklist_text below.
_DECKLIST_LINE_RE = re.compile(r"^\s*(\d+)x?\s+(.+?)\s*$")


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
    *, api_key: str, start: date, end: date, game: str = GAME, format: str = FORMAT
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


def refresh_topdeck(
    conn,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_age_seconds: float = MAX_AGE_SECONDS,
    force: bool = False,
) -> RefreshResult:
    """Update the Standard corpus from TopDeck.gg if configured and stale.
    Never raises. No credential configured is reported as its own status,
    not folded into "failed" — a missing opt-in key is not an error."""
    from sensei_top.metagame.source import cache_age_seconds

    config = load_config()
    if config is None:
        return RefreshResult(status="not_configured")

    age = cache_age_seconds(conn, source="topdeck")
    if not force and age is not None and age < max_age_seconds:
        return RefreshResult(status="fresh", age_seconds=age)

    end = datetime.now(UTC).date()
    start = end - timedelta(days=window_days)

    try:
        tournaments = list_tournaments(api_key=config.api_key, start=start, end=end)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        log.warning("topdeck refresh failed, keeping the cached copy: %s", exc)
        return RefreshResult(status="failed", age_seconds=age, error=str(exc))

    known = already_fetched(conn)
    events = []
    skipped = 0
    for tournament in tournaments:
        tid = tournament.get("TID")
        if not tid:
            skipped += 1
            continue
        raw = _normalize(tournament)
        blob_sha = _blob_sha(raw)
        # Namespaced like fbettega's own "Tournaments/<source>/..." layout —
        # not just for uniqueness (already-fetched dedup keys on the full
        # path) but because parse_event derives ParsedEvent.source from
        # path.split("/", 2)[1], so this shape is what makes a TopDeck event
        # report source="Topdeck" rather than the TID filename itself.
        path = f"Tournaments/Topdeck/{tid}.json"
        if known.get(path) == blob_sha:
            continue
        parsed = parse_event(raw, TournamentFile(path=path, blob_sha=blob_sha))
        if parsed is None:
            skipped += 1
            continue
        events.append(parsed)

    store_events(conn, events)
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            INSERT INTO meta_fetch_source (source, ref, fetched_at, window_days, events, skipped)
                 VALUES ('topdeck', ?, ?, ?, ?, ?)
            ON CONFLICT (source) DO UPDATE SET
                 ref = excluded.ref, fetched_at = excluded.fetched_at,
                 window_days = excluded.window_days, events = excluded.events,
                 skipped = excluded.skipped
            """,
            (API_BASE, fetched_at, window_days, len(events), skipped),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return RefreshResult(status="updated", events=len(events), skipped=skipped, age_seconds=age)
