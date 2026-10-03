"""Standard results read straight from mtgo.com's decklist pages — a third
source for the corpus, added because the fbettega mirror lagged days behind
the site (measured 2026-10-03). Same discipline as ``topdeck.py``: normalise
a page's embedded data into the ``CacheItem`` shape ``source.parse_event``
already parses, then store through the existing path, so tiering, dedup and
the handle-dropping privacy guarantee are inherited, not re-implemented. A
player handle is only ever a join key inside this module's output; it never
reaches SQLite.

Each event page embeds ``window.MTGO.decklists.data = {...};`` on one line. A
challenge carries ``decklists``, ``standings``, ``winloss``, ``final_rank``
and ``brackets``; a league carries only ``decklists`` with a ``wins``/``losses``
record per deck. The stored path is fbettega's own
(``Tournaments/MTGO/YYYY/MM/DD/<site_name>.json``), so a later mirror refresh
of the same event replaces this copy by ``event_id``.

Fetching is paced and limited to results pages, with a descriptive
User-Agent; the terms reading is in ``docs/attribution.md``. Fail-soft: a
network error keeps what is stored.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sensei_top.metagame.source import (
    RefreshResult,
    TournamentFile,
    already_fetched,
    cache_age_seconds,
    parse_event,
    store_events,
)

log = logging.getLogger(__name__)

SITE = "https://www.mtgo.com"
INDEX_URL = f"{SITE}/decklists"
FORMAT_PREFIX = "standard-"
USER_AGENT = "sensei-top/0.1 (+local analytics; results pages only)"
# Challenge pages run past 300 KB and timed out at 30 s on a real run.
TIMEOUT = 90.0
MAX_AGE_SECONDS = 3 * 3600

_SLUG_RE = re.compile(r'href="/decklist/([^"#?/]+)"')
_DATA_MARKER = "window.MTGO.decklists.data"
_SLUG_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_BRACKET_ROUNDS = {4: "Quarterfinals", 2: "Semifinals", 1: "Finals"}


def fetch_page(url: str, *, timeout: float = TIMEOUT) -> str:
    """The only networked function: one GET of a results page."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def fetch_with_retry(
    fetch: Callable[[str], str], url: str, *, pause_s: float, sleep: Callable[[float], None]
) -> str:
    """One retry on a timeout or URL error, after at most ``pause_s``."""
    try:
        return fetch(url)
    except (TimeoutError, urllib.error.URLError):
        sleep(pause_s)
        return fetch(url)


def list_event_slugs(html: str) -> list[str]:
    """Every Standard event slug linked from the index, de-duplicated, in
    page order."""
    seen: dict[str, None] = {}
    for slug in _SLUG_RE.findall(html):
        if slug.startswith(FORMAT_PREFIX):
            seen.setdefault(slug)
    return list(seen)


def extract_data(html: str) -> dict[str, Any] | None:
    """The JSON object after ``window.MTGO.decklists.data =``, or ``None``
    when it is absent or unreadable. Never raises."""
    start = html.find(_DATA_MARKER)
    if start < 0:
        return None
    eq = html.find("=", start + len(_DATA_MARKER))
    if eq < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html[eq + 1:].lstrip())
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ordinal(rank: int) -> str:
    # fbettega's wording: only 1-3 get a special suffix ("21th Place").
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank, "th")
    return f"{rank}{suffix} Place"


def _cards(section: Any) -> list[dict[str, Any]]:
    """Sum ``qty`` per card name, sorted by name as the mirror writes them."""
    totals: dict[str, int] = {}
    for entry in section or []:
        if not isinstance(entry, dict):
            continue
        attrs = entry.get("card_attributes")
        name = attrs.get("card_name") if isinstance(attrs, dict) else None
        if not isinstance(name, str) or not name:
            continue
        totals[name] = totals.get(name, 0) + _int(entry.get("qty"))
    return [{"Count": n, "CardName": name} for name, n in sorted(totals.items())]


def normalize(data: dict[str, Any]) -> dict[str, Any]:
    """One page's data -> one ``CacheItem``-shaped dict. The ``Formats`` of an
    event that is not Standard is left as the site's own code, so
    ``parse_event`` skips it."""
    site_name = str(data.get("site_name") or "")
    starttime = data.get("starttime") or data.get("publish_date")
    date = str(starttime)[:10] if starttime else None
    fmt = data.get("format")
    is_league = "standings" not in data and "final_rank" not in data
    if fmt is None:
        # A league page names no format; its slug does.
        fmt = "CSTANDARD" if site_name.startswith(FORMAT_PREFIX) else "unknown"
    tournament = {
        "Date": date,
        "Name": data.get("description") or data.get("name"),
        "Uri": f"{SITE}/decklist/{site_name}" if site_name else None,
        "Formats": "Standard" if fmt == "CSTANDARD" else fmt,
    }

    decklists = [d for d in data.get("decklists") or [] if isinstance(d, dict)]
    final_rank = {
        str(r.get("loginid")): _int(r.get("rank"))
        for r in data.get("final_rank") or []
        if isinstance(r, dict)
    }
    # Placement order when the page has one; otherwise page order.
    if final_rank:
        far = len(decklists) + max(final_rank.values(), default=0) + 1
        decklists = sorted(
            decklists, key=lambda d: final_rank.get(str(d.get("loginid")), far)
        )

    decks: list[dict[str, Any]] = []
    for deck in decklists:
        player = deck.get("player")
        if not isinstance(player, str) or not player:
            continue
        rank = final_rank.get(str(deck.get("loginid")))
        if rank:
            result: str | None = _ordinal(rank)
        elif is_league and isinstance(deck.get("wins"), dict):
            # A league deck's record is a nested object: {wins, losses, ...}.
            record = deck["wins"]
            result = f"{_int(record.get('wins'))}-{_int(record.get('losses'))}"
        else:
            result = None
        decks.append({
            "Date": date,
            "Player": player,
            "Result": result,
            "Mainboard": _cards(deck.get("main_deck")),
            "Sideboard": _cards(deck.get("sideboard_deck")),
        })

    winloss = {
        str(w.get("loginid")): w for w in data.get("winloss") or [] if isinstance(w, dict)
    }
    standings: list[dict[str, Any]] = []
    rows = [s for s in data.get("standings") or [] if isinstance(s, dict)]
    for row in sorted(rows, key=lambda s: _int(s.get("rank"), 10**6)):
        record = winloss.get(str(row.get("loginid")))
        player = row.get("login_name")
        if record is None or not isinstance(player, str):
            continue
        standings.append({
            "Rank": _int(row.get("rank")),
            "Player": player,
            "Points": _int(row.get("score")),
            "Wins": _int(record.get("wins")),
            "Losses": _int(record.get("losses")),
            "Draws": 0,
            "OMWP": _float(row.get("opponentmatchwinpercentage")),
            "GWP": _float(row.get("gamewinpercentage")),
            "OGWP": _float(row.get("opponentgamewinpercentage")),
        })

    rounds: list[dict[str, Any]] = []
    brackets = [b for b in data.get("brackets") or [] if isinstance(b, dict)]
    brackets.sort(key=lambda b: -len(b.get("matches") or []))
    for bracket in brackets:
        matches_in = bracket.get("matches") or []
        name = _BRACKET_ROUNDS.get(len(matches_in))
        if name is None:
            continue
        matches = []
        for match in matches_in:
            players = match.get("players") if isinstance(match, dict) else None
            if not isinstance(players, list) or len(players) != 2:
                continue
            a, b = players
            matches.append({
                "Player1": a.get("player"),
                "Player2": b.get("player"),
                "Result": f"{_int(a.get('wins'))}-{_int(b.get('wins'))}-0",
            })
        rounds.append({"RoundName": name, "Matches": matches})

    return {"Tournament": tournament, "Decks": decks, "Standings": standings, "Rounds": rounds}


def _path_for(slug: str) -> str | None:
    match = _SLUG_DATE_RE.search(slug)
    if match is None:
        return None
    year, month, day = match.groups()
    return f"Tournaments/MTGO/{year}/{month}/{day}/{slug}.json"


def _blob_sha(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def refresh_mtgo_site(
    conn,
    *,
    max_pages: int = 40,
    pause_s: float = 1.0,
    force: bool = False,
    max_age_seconds: float = MAX_AGE_SECONDS,
    fetch: Callable[[str], str] = fetch_page,
    sleep: Callable[[float], None] = time.sleep,
) -> RefreshResult:
    """Fetch new Standard events from mtgo.com. Never raises."""
    age = cache_age_seconds(conn, source="mtgo")
    if not force and age is not None and age < max_age_seconds:
        return RefreshResult(status="fresh", age_seconds=age)

    try:
        index_html = fetch_with_retry(fetch, INDEX_URL, pause_s=pause_s, sleep=sleep)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError,
            http.client.HTTPException) as exc:
        log.warning("mtgo.com refresh failed, keeping the cached copy: %s", exc)
        return RefreshResult(status="failed", age_seconds=age, error=str(exc))
    if "/decklist/" not in index_html:
        # A 200 with no event links is a changed page, not an empty day.
        log.warning("mtgo.com index carried no decklist links, keeping the cached copy")
        return RefreshResult(status="failed", age_seconds=age, error="no decklist links found")
    slugs = list_event_slugs(index_html)

    known = already_fetched(conn)
    today = datetime.now(UTC).date()
    recent = {today.isoformat(), (today - timedelta(days=1)).isoformat()}
    todo: list[tuple[str, str]] = []
    for slug in slugs:
        path = _path_for(slug)
        if path is None:
            continue
        slug_date = "-".join(path.split("/")[2:5])
        if path in known and slug_date not in recent:
            continue
        todo.append((slug, path))

    events = []
    skipped = 0
    for i, (slug, path) in enumerate(todo[:max_pages]):
        if i:
            sleep(pause_s)
        try:
            data = extract_data(
                fetch_with_retry(fetch, f"{SITE}/decklist/{slug}", pause_s=pause_s, sleep=sleep)
            )
            if data is None:
                skipped += 1
                continue
            raw = normalize(data)
            parsed = parse_event(raw, TournamentFile(path=path, blob_sha=_blob_sha(raw)))
        except Exception as exc:  # one bad page must never stop the refresh
            log.warning("mtgo.com page %s skipped: %s", slug, exc)
            skipped += 1
            continue
        if parsed is None:
            skipped += 1
            continue
        if known.get(path) == parsed.blob_sha:
            continue
        events.append(parsed)

    store_events(conn, events)
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            INSERT INTO meta_fetch_source (source, ref, fetched_at, window_days, events, skipped)
                 VALUES ('mtgo', ?, ?, NULL, ?, ?)
            ON CONFLICT (source) DO UPDATE SET
                 ref = excluded.ref, fetched_at = excluded.fetched_at,
                 window_days = excluded.window_days, events = excluded.events,
                 skipped = excluded.skipped
            """,
            (INDEX_URL, fetched_at, len(events), skipped),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return RefreshResult(status="updated", events=len(events), skipped=skipped, age_seconds=age)
