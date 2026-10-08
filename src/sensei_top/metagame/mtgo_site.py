"""Results read straight from mtgo.com's decklist pages — a third
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

A run (plan 14, S4) passes the source's hold first (``holds.gate``), then
reads the index, the month pages a gap needs and the event pages, one second
apart, and stops rather than adapts when the site answers with something
other than a page — the answers table in ``docs/metagame.md``.

The event pages are read newest first, at most 40, from three lists: the
index's slugs not stored yet; a month page's (``/decklists/YYYY/MM``) not
stored yet and dated on or after its format's start; and the stored leagues
R3 reads again (D10), today's on every run and yesterday's once after 12:00
UTC, because leagues republish through the day. A format's start is the day
of the last completed run or, with none, of the format's newest stored MTGO
event; never before the format's window (``guide.window``), and never more
than 90 days back. Month pages run from the earliest start's month through
the previous month, newest first, while the list is under 40, so after a
completed run this month there are none. Traps this module exists to avoid:

1. **An HTTP status is never sent again.** ``HTTPError`` is a ``URLError``,
   so catching the one retries the other; only a timeout, or a URL error
   that is not an HTTP status, is retried, once.
2. **An answer ends the run but keeps what it parsed.** Events read before
   it are stored, and the answer goes to ``holds.apply_outcome``; only a run
   that completed stamps ``meta_fetch_source('mtgo')``.
3. **A page that is gone is not an answer.** A 404 or 410 at a month or
   event page, or a redirect away from it (D19: the site answers a removed
   event that way), skips the page and stamps a stored event ``'gone'``. The
   index is not special-cased: a 404 there is a generic answer, and a
   redirect is followed and read as the index.
4. **Three unparsable pages in a row end the run as a completed one** (k8),
   so a changed layout costs four requests, not forty. A gone page neither
   counts towards the three nor breaks the row; another format's page does
   break it, since its data read.
5. **The clock is read when each answer arrives.** A ``Retry-After`` in
   seconds counts from then, and a run can last minutes; timing it from the
   run's start would let the next attempt come before the site's time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sensei_top.formats import FORMATS
from sensei_top.metagame.holds import (
    MTGO,
    TIME_FORMAT,
    Gate,
    apply_outcome,
    gate,
    parse_retry_after,
    read_hold,
)
from sensei_top.metagame.source import (
    FETCH_FORMATS,
    Answer,
    AnswerKind,
    ParsedEvent,
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
from sensei_top.mtgo.formats import FORMAT_CODES

log = logging.getLogger(__name__)

SITE = "https://www.mtgo.com"
INDEX_URL = f"{SITE}/decklists"
USER_AGENT = "sensei-top/0.1 (+local analytics; results pages only)"
# Challenge pages run past 300 KB and timed out at 30 s on a real run.
TIMEOUT = 90.0
MAX_AGE_SECONDS = 3 * 3600

_SLUG_RE = re.compile(r'href="/decklist/([^"#?/]+)"')
_DATA_MARKER = "window.MTGO.decklists.data"
_SLUG_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# A stored MTGO event's path: its slug's day, then the slug.
_STORED_PATH_RE = re.compile(r"^Tournaments/MTGO/(\d{4})/(\d{1,2})/(\d{1,2})/([^/]+)\.json$")
# ``meta_event.source`` of an MTGO event, whichever copy stored it.
_MTGO_EVENTS = "MTGO"
# The gap's floor (S4): no format starts further back than this, and one
# with no detected reset starts here.
GAP_DAYS = 90
_BRACKET_ROUNDS = {4: "Quarterfinals", 2: "Semifinals", 1: "Finals"}

# A month or event page answered with one of these is skipped, never an
# Answer; at the index they are generic (S3).
GONE_STATUSES = frozenset({404, 410})
# k8: this many unparsable event pages in a row end the run as completed.
UNPARSABLE_IN_A_ROW = 3
INDEX_PLACE = "index"
# An index with no event link is a changed page, not an empty day: generic.
NO_LINKS = "no decklist links found"


class RedirectedError(Exception):
    """A page answered with a redirect away from the address requested.
    ``urllib`` follows redirects on its own; this is how ``fetch_page`` says
    it did. ``body`` is what the landing page sent, which only the index
    reads (D19)."""

    def __init__(self, url: str, final_url: str, body: bytes) -> None:
        super().__init__(f"redirected to {final_url}")
        self.url = url
        self.final_url = final_url
        self.body = body


def fetch_page(url: str, *, timeout: float = TIMEOUT) -> str:
    """The only networked function: one GET of a results page. Raises
    ``RedirectedError`` when the page it read is not at ``url``."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        final_url = response.geturl()
    if final_url != url:
        raise RedirectedError(url, final_url, body)
    return body.decode("utf-8")


def fetch_with_retry(
    fetch: Callable[[str], str], url: str, *, pause_s: float, sleep: Callable[[float], None]
) -> str:
    """One retry, after ``pause_s``, on a timeout or a URL error that is not
    an HTTP status. An ``HTTPError`` is the site's answer and is never sent
    again (defect 2); a second failure propagates."""
    try:
        return fetch(url)
    except urllib.error.HTTPError:
        raise
    except (TimeoutError, urllib.error.URLError):
        sleep(pause_s)
        return fetch(url)


def list_event_slugs(html: str, formats: Sequence[str] = FETCH_FORMATS) -> list[str]:
    """Every event slug of ``formats`` linked from the index, de-duplicated,
    in page order. A slug is of a format when it starts with the lower-cased
    name and a hyphen, so ``premodern-`` never matches ``modern-``."""
    prefixes = tuple(f"{fmt.lower()}-" for fmt in formats)
    seen: dict[str, None] = {}
    for slug in _SLUG_RE.findall(html):
        if slug.startswith(prefixes):
            seen.setdefault(slug)
    return list(seen)


def _slug_format(slug: str) -> str | None:
    """The format a slug names, among all seven, or ``None``."""
    for fmt in FORMATS:
        if slug.startswith(f"{fmt.lower()}-"):
            return fmt
    return None


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
    """One page's data -> one ``CacheItem``-shaped dict. The site's format
    code (``C<NAME>``) becomes the format name by ``FORMAT_CODES``; a code the
    table does not know stays as the site gave it, so ``parse_event`` skips
    it."""
    site_name = str(data.get("site_name") or "")
    starttime = data.get("starttime") or data.get("publish_date")
    date = str(starttime)[:10] if starttime else None
    fmt = data.get("format")
    is_league = "standings" not in data and "final_rank" not in data
    if fmt is None:
        # A league page names no format; its slug does.
        fmt = _slug_format(site_name) or "unknown"
    tournament = {
        "Date": date,
        "Name": data.get("description") or data.get("name"),
        "Uri": f"{SITE}/decklist/{site_name}" if site_name else None,
        "Formats": FORMAT_CODES.get(fmt, fmt),
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


def _day(path: str) -> date | None:
    """The day of a stored MTGO path, which is its slug's; None for another
    path or an impossible date."""
    match = _STORED_PATH_RE.match(path)
    if match is None:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def _iso_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(t: datetime) -> str:
    return t.astimezone(UTC).strftime(TIME_FORMAT)


def _last_completed(conn: sqlite3.Connection) -> datetime | None:
    """The stamp of the last completed run, ``meta_fetch_source('mtgo')``,
    or None when there is none or it does not parse."""
    row = conn.execute(
        "SELECT fetched_at FROM meta_fetch_source WHERE source = ?", (MTGO,)
    ).fetchone()
    if row is None or not row[0]:
        return None
    try:
        return datetime.strptime(row[0], TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _stored_age(conn: sqlite3.Connection, at: datetime) -> float | None:
    """``cache_age_seconds(conn, source="mtgo")`` on the run's clock: seconds
    from the last completed run's stamp to ``at``, or None with no stamp."""
    fetched = _last_completed(conn)
    return None if fetched is None else (at - fetched).total_seconds()


class _AnswerError(Exception):
    """The site answered with something other than a page; ``answer`` ends
    the run."""

    def __init__(self, answer: Answer) -> None:
        super().__init__(answer.reason)
        self.answer = answer


class _UnparsableError(Exception):
    """An event page that opened, but whose data did not decode or
    normalise."""


def _answer(exc: BaseException, *, place: str, first_request: bool, at: datetime) -> Answer:
    """The ``Answer`` a failed fetch makes: an HTTP status by its kind, with
    its ``Retry-After`` read against ``at``, when it arrived; anything else
    generic."""
    if isinstance(exc, urllib.error.HTTPError):
        headers = exc.headers
        retry_after = parse_retry_after(
            headers.get("Retry-After") if headers is not None else None, at=at
        )
        return Answer(
            kind=answer_kind(exc.code), reason=answer_reason(exc), at=at,
            http_status=exc.code, place=place, retry_after=retry_after,
            first_request=first_request,
        )
    return Answer(
        kind=AnswerKind.GENERIC, reason=answer_reason(exc), at=at, place=place,
        first_request=first_request,
    )


class _Requests:
    """One run's requests: paced, counted (an answer to the run's very first
    request is the one the 503 day rule counts, k2), and turned into an
    ``_AnswerError`` when the site says anything other than a page."""

    def __init__(
        self,
        fetch: Callable[[str], str],
        *,
        pause_s: float,
        sleep: Callable[[float], None],
        now: Callable[[], datetime],
    ) -> None:
        self._fetch = fetch
        self._pause_s = pause_s
        self._sleep = sleep
        self._now = now
        self.sent = 0

    def _get(self, url: str) -> str:
        self.sent += 1
        return self._fetch(url)

    def _follow(self, url: str) -> str:
        try:
            return self._get(url)
        except RedirectedError as exc:
            return exc.body.decode("utf-8")

    def _ended(self, exc: BaseException, place: str) -> _AnswerError:
        return _AnswerError(
            _answer(exc, place=place, first_request=self.sent == 1, at=self._now())
        )

    def index(self) -> str:
        """The index, wherever a redirect lands. Raises ``_AnswerError`` for
        any failure, and for an index with no event link."""
        try:
            html = fetch_with_retry(
                self._follow, INDEX_URL, pause_s=self._pause_s, sleep=self._sleep
            )
        except Exception as exc:  # every way the index fails ends the run
            raise self._ended(exc, INDEX_PLACE) from exc
        if "/decklist/" not in html:
            raise _AnswerError(Answer(
                kind=AnswerKind.GENERIC, reason=NO_LINKS, at=self._now(),
                place=INDEX_PLACE, first_request=self.sent == 1,
            ))
        return html

    def page(self, url: str, place: str) -> str | None:
        """A page after the index, one pause after the request before it:
        its text, or None when it is gone (a 404 or 410, or a redirect away
        from ``url``). Raises ``_AnswerError`` when the site's answer ends the
        run, and ``UnicodeDecodeError`` for a page that came back unreadable,
        which is the caller's to judge."""
        self._sleep(self._pause_s)
        try:
            return fetch_with_retry(self._get, url, pause_s=self._pause_s, sleep=self._sleep)
        except RedirectedError as exc:
            log.warning("mtgo.com %s skipped: redirected to %s", place, exc.final_url)
            return None
        except urllib.error.HTTPError as exc:
            if exc.code not in GONE_STATUSES:
                raise self._ended(exc, place) from exc
            log.warning("mtgo.com %s skipped: %s", place, answer_reason(exc))
            return None
        except UnicodeDecodeError:
            raise
        except Exception as exc:  # a timeout twice, no connection, anything else
            raise self._ended(exc, place) from exc


@dataclass
class _Outcome:
    """What a run read. ``reads`` are ``(event_id, outcome)`` stamps for
    stored events that were read but not stored again; ``page_read`` is
    whether the index opened (k1)."""

    events: list[ParsedEvent] = field(default_factory=list)
    skipped: int = 0
    reads: list[tuple[str, str]] = field(default_factory=list)
    page_read: bool = False
    answer: Answer | None = None


def _format_of(slug: str, formats: Sequence[str]) -> str | None:
    """The one of ``formats`` a slug is of, by ``list_event_slugs``' rule."""
    for fmt in formats:
        if slug.startswith(f"{fmt.lower()}-"):
            return fmt
    return None


def _unknown_slugs(
    html: str,
    known: Mapping[str, str],
    formats: Sequence[str],
    since: Mapping[str, date] | None = None,
) -> list[tuple[str, str]]:
    """``(slug, path)`` for a page's slugs of ``formats`` not stored yet, in
    page order. With ``since``, only those whose slug is dated on or after
    their format's day there."""
    found: list[tuple[str, str]] = []
    for slug in list_event_slugs(html, formats):
        path = _path_for(slug)
        if path is None or path in known:
            continue
        if since is not None:
            day, fmt = _day(path), _format_of(slug, formats)
            if day is None or fmt is None or day < since[fmt]:
                continue
        found.append((slug, path))
    return found


def _rereads(
    conn: sqlite3.Connection, formats: Sequence[str], started: datetime
) -> list[tuple[str, str]]:
    """R3 (D10): the stored leagues read again, as ``(slug, path)`` — today's
    (UTC) on every run, and yesterday's once at or after 12:00 UTC, while the
    later of its two read stamps is before today's 12:00 (an unstamped read
    counts as before). Only MTGO leagues (tier C) of ``formats`` that are not
    a duplicate. A league's day is its path's, the slug its address is built
    from, not ``event_date``, which is the page's own."""
    if not formats:
        return []
    today = started.astimezone(UTC).date()
    noon = datetime(today.year, today.month, today.day, 12, tzinfo=UTC)
    before_noon = _stamp(noon)
    marks = ", ".join("?" for _ in formats)
    rows = conn.execute(
        "SELECT path, lists_read_at, empty_read_at FROM meta_event "
        "WHERE source = ? AND tier = 'C' AND duplicate_of IS NULL "
        f"AND format IN ({marks}) ORDER BY path",
        (_MTGO_EVENTS, *formats),
    ).fetchall()
    again: list[tuple[str, str]] = []
    for path, lists_at, empty_at in rows:
        match = _STORED_PATH_RE.match(path)
        day = _day(path)
        if match is None or day is None:
            continue
        if day == today or (
            day == today - timedelta(days=1)
            and started >= noon
            and max(lists_at or "", empty_at or "") < before_noon
        ):
            again.append((match[4], path))
    return again


def _starts(
    conn: sqlite3.Connection, formats: Sequence[str], today: date, last_run: datetime | None
) -> dict[str, date]:
    """``start(F)`` for each followed format (S4, "The gap"): the day of the
    last completed run when there is one, otherwise the day of the format's
    newest stored MTGO event that is not a duplicate; never before the
    format's window (the day after its newest detected reset), and never
    more than ``GAP_DAYS`` before ``today``, which is also the window of a
    format with no reset."""
    # Imported here, not at the top: guide imports metagame (rcq.py, and
    # review/ under it), so loading guide with this module would close a
    # package cycle, and pull every guide and review module into each import
    # of metagame.
    from sensei_top.guide.window import format_resets, window_start

    floor = today - timedelta(days=GAP_DAYS)
    starts: dict[str, date] = {}
    for fmt in formats:
        resets = format_resets(conn, fmt)
        window = _iso_day(window_start(resets[0])) if resets else None
        start = window or floor
        if last_run is not None:
            start = max(start, last_run.astimezone(UTC).date())
        else:
            newest = _iso_day(conn.execute(
                "SELECT MAX(substr(event_date, 1, 10)) FROM meta_event "
                "WHERE source = ? AND duplicate_of IS NULL AND format = ?",
                (_MTGO_EVENTS, fmt),
            ).fetchone()[0])
            if newest is not None:
                start = max(start, newest)
        starts[fmt] = max(start, floor)
    return starts


def _gap_months(first: date, today: date) -> list[tuple[int, int]]:
    """``(year, month)`` from the month before ``today``'s back to
    ``first``'s, newest first: none when ``first`` is in ``today``'s month."""
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    while True:
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
        if (year, month) < (first.year, first.month):
            return months
        months.append((year, month))


def _fill_gap(
    conn: sqlite3.Connection,
    requests: _Requests,
    work: dict[str, str],
    *,
    known: Mapping[str, str],
    formats: Sequence[str],
    started: datetime,
    max_pages: int,
) -> None:
    """Add the month pages' unknown slugs the gap needs to ``work`` (path ->
    slug), newest month first, while ``work`` holds under ``max_pages``. A
    month page gone, redirected, unreadable or with no link is skipped with a
    warning; any other answer raises ``_AnswerError``."""
    today = started.astimezone(UTC).date()
    last_run = _last_completed(conn)
    # After a completed run this month every start is in this month, so no
    # month page is read, and the formats' windows need not be computed.
    if last_run is not None and last_run.astimezone(UTC).date() >= today.replace(day=1):
        return
    starts = _starts(conn, formats, today, last_run)
    if not starts:
        return
    for year, month in _gap_months(min(starts.values()), today):
        if len(work) >= max_pages:
            return
        place = f"month:{year:04d}-{month:02d}"
        try:
            html = requests.page(f"{INDEX_URL}/{year:04d}/{month:02d}", place)
        except UnicodeDecodeError as exc:
            log.warning("mtgo.com %s skipped, unreadable: %s", place, exc)
            continue
        if html is None:
            continue  # gone or redirected; ``requests.page`` has said so
        if "/decklist/" not in html:
            log.warning("mtgo.com %s skipped: %s", place, NO_LINKS)
            continue
        for slug, path in _unknown_slugs(html, known, formats, since=starts):
            work.setdefault(path, slug)


def _newest_first(work: Mapping[str, str]) -> list[tuple[str, str]]:
    """``work`` (path -> slug) as ``(slug, path)``, the newest slug day
    first; a day's pages keep the order they were added in (the index's,
    then R3's, then the month pages')."""
    return sorted(
        ((slug, path) for path, slug in work.items()),
        key=lambda item: _day(item[1]) or date.min,
        reverse=True,  # still a stable sort: ties keep their order
    )


def _read_event(html: str, path: str, formats: Sequence[str]) -> ParsedEvent | None:
    """One event page as a ``ParsedEvent``, or None for an event of another
    format. Raises ``_UnparsableError`` when it has no data script, or data
    that does not decode or normalise."""
    data = extract_data(html)
    if data is None:
        raise _UnparsableError("no readable data script")
    try:
        raw = normalize(data)
        return parse_event(raw, TournamentFile(path=path, blob_sha=_blob_sha(raw)), formats)
    except Exception as exc:  # a changed layout costs this page, not the run
        raise _UnparsableError(f"{type(exc).__name__}: {exc}") from exc


def _read_site(
    conn: sqlite3.Connection,
    requests: _Requests,
    *,
    formats: Sequence[str],
    max_pages: int,
    started: datetime,
) -> _Outcome:
    out = _Outcome()
    try:
        index_html = requests.index()
    except _AnswerError as ended:
        out.answer = ended.answer
        return out
    out.page_read = True

    known = already_fetched(conn)
    work: dict[str, str] = {}  # path -> slug, the event pages to read
    for slug, path in [
        *_unknown_slugs(index_html, known, formats), *_rereads(conn, formats, started)
    ]:
        work.setdefault(path, slug)
    try:
        _fill_gap(
            conn, requests, work, known=known, formats=formats, started=started,
            max_pages=max_pages,
        )
    except _AnswerError as ended:
        out.answer = ended.answer
        return out

    unparsable = 0
    for slug, path in _newest_first(work)[:max_pages]:
        try:
            html = requests.page(f"{SITE}/decklist/{slug}", f"event:{slug}")
            event = _read_event(html, path, formats) if html is not None else None
        except _AnswerError as ended:
            out.answer = ended.answer
            return out
        except (_UnparsableError, UnicodeDecodeError) as exc:
            log.warning("mtgo.com page %s skipped, unparsable: %s", slug, exc)
            out.skipped += 1
            unparsable += 1
            if unparsable >= UNPARSABLE_IN_A_ROW:
                log.warning(
                    "mtgo.com: %d event pages in a row were unparsable; ending the run",
                    unparsable,
                )
                break
            continue
        if html is None:
            out.skipped += 1
            if path in known:
                out.reads.append((path, "gone"))
            continue
        unparsable = 0
        if event is None:
            out.skipped += 1  # another format's event
            continue
        if known.get(path) == event.blob_sha:
            out.reads.append((path, "lists" if has_lists(event) else "empty"))
            continue
        out.events.append(event)
    return out


def refresh_mtgo_site(
    conn,
    *,
    max_pages: int = 40,
    pause_s: float = 1.0,
    force: bool = False,
    max_age_seconds: float = MAX_AGE_SECONDS,
    fetch: Callable[[str], str] = fetch_page,
    sleep: Callable[[float], None] = time.sleep,
    formats: Sequence[str] = FETCH_FORMATS,
    now: Callable[[], datetime] = _utc_now,
    by_hand: bool = False,
) -> RefreshResult:
    """Fetch new events of ``formats`` from mtgo.com, through the source's
    hold (plan 14, S3 and S4).

    ``now`` is the run's clock, an aware UTC time read at the start, when an
    answer arrives and at the end. ``by_hand`` is whether the user ran it
    rather than the server's loop; only the gate reads it.

    ``held`` and ``fresh`` make no request. Otherwise the run reads the
    index, the month pages a gap needs and at most ``max_pages`` event pages
    (the module docstring), and completes
    (``updated``, stamped, the hold lifted) or the site's answer ends it
    (``failed``, ``error`` the answer's reason, unstamped). Either way it
    stores what it parsed, and ``events`` counts what ``store_events``
    stored. Every result carries the hold before and after the run and the
    stored copy's age at its end. A failed request never raises.
    """
    started = now()
    before = read_hold(conn, MTGO)
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

    requests = _Requests(fetch, pause_s=pause_s, sleep=sleep, now=now)
    out = _read_site(conn, requests, formats=formats, max_pages=max_pages, started=started)
    answer = out.answer
    if answer is not None:
        log.warning(
            "mtgo.com answered %s at %s; ending the run, keeping what it parsed",
            answer.reason, answer.place,
        )

    # Every read in this run is stamped with its start: a page read just
    # after it is never recorded as read later than it was.
    read_at = _stamp(started)
    stored = store_events(conn, out.events, now=read_at)
    skipped = out.skipped + len(out.events) - stored
    ended = now()
    conn.execute("BEGIN")
    try:
        for event_id, outcome in out.reads:
            record_read(conn, event_id, outcome=outcome, now=read_at)
        after = apply_outcome(
            conn, MTGO, before=before, answer=answer, page_read=out.page_read,
            completed=answer is None, now=answer.at if answer is not None else ended,
        )
        if answer is None:
            conn.execute(
                """
                INSERT INTO meta_fetch_source
                     (source, ref, fetched_at, window_days, events, skipped)
                     VALUES (?, ?, ?, NULL, ?, ?)
                ON CONFLICT (source) DO UPDATE SET
                     ref = excluded.ref, fetched_at = excluded.fetched_at,
                     window_days = excluded.window_days, events = excluded.events,
                     skipped = excluded.skipped
                """,
                (MTGO, INDEX_URL, _stamp(ended), stored, skipped),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    result = RefreshResult(
        status="updated", events=stored, skipped=skipped,
        age_seconds=_stored_age(conn, ended), hold_before=before, hold_after=after,
        by_hand=by_hand,
    )
    if answer is None:
        return result
    return replace(result, status="failed", error=answer.reason, answer=answer)
