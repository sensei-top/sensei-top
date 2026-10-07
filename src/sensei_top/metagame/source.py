"""Tournament results from ``fbettega/MTG_decklistcache`` — the project's
third and fourth downloads (outbound calls five and six in AGENTS.md rule 5:
one to the GitHub API for a tree listing, one per selected file to
``raw.githubusercontent.com``).

Unlike ``archetypes/source.py``'s one-shot tarball, this cache is ~157 MB —
years of tournament history across sources this project never reads
(``Topdeck`` and ``Manatrader`` are both dead in this cache, stopped at 2025
and 2024 respectively). Fetching all of it on every refresh would be waste on
a scale the archetype download never approaches, so this module is windowed
by date and incremental by content: one GitHub API call lists the whole
repository's file tree at a pinned commit, a date-and-source filter picks out
what is worth reading, and each file's own blob SHA decides whether it needs
fetching again at all.

Like ``archetypes/source.py``, every call here is a bare GET — no query
string, no body — and nothing about a match, a deck or the user reaches
either URL: the paths this module builds name dates and tournament sources,
never anything from ``Player.log``.

Failure is never fatal. A refresh that cannot reach GitHub keeps whatever it
already has and says how old that is; one unreadable file upstream is
skipped and counted, never the whole refresh.

Privacy: a cache decklist carries the real MTGO/Melee handle of a third
party. AGENTS.md's privacy rule forbids real identifiers in tracked files, so
``parse_event`` resolves ``Player`` to a per-event ordinal and discards the
name — it never reaches ``store_events``, let alone SQLite.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from sensei_top.formats import FORMATS
from sensei_top.metagame.tiers import classify_tier

if TYPE_CHECKING:
    # holds.py imports Answer from here; the reverse import is for typing only.
    from sensei_top.metagame.holds import Hold

log = logging.getLogger(__name__)

OWNER = "fbettega"
REPO = "MTG_decklistcache"
API_BASE = f"https://api.github.com/repos/{OWNER}/{REPO}"
RAW_BASE = f"https://raw.githubusercontent.com/{OWNER}/{REPO}"
HEADERS = {"User-Agent": "sensei-top/0.1", "Accept": "application/vnd.github+json"}
TIMEOUT = 30.0

# Topdeck and Manatrader are dead in this cache (stopped at 2025 and 2024).
# CardsRealm was never evaluated by the source document. Adding a live source
# here is the whole change.
SOURCES: tuple[str, ...] = ("MTGO", "MTGmelee")

# The formats every refresh fetches, stored or not (plan 13, D10). The server's
# loop and ``meta`` follow these, every format the stored corpus already
# holds, and any ``--format X`` the user names (plan 14, D2, D8):
# ``metagame/auto.py::followed_formats``. Nothing reads the user's own
# matches to widen it.
FETCH_FORMATS: tuple[str, ...] = ("Standard", "Modern")

DEFAULT_WINDOW_DAYS = 90
# A hard ceiling so a misconfigured window (or a future source with a much
# higher publishing rate) can never turn one refresh into thousands of GETs.
MAX_FILES_PER_REFRESH = 2000

_PATH_RE = re.compile(r"^Tournaments/([^/]+)/(\d{4})/(\d{1,2})/(\d{1,2})/[^/]+\.json$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _filename_formats(path: str, formats: Sequence[str]) -> list[str]:
    """Every one of ``formats`` that is a whole token of the file's name:
    ``premodern-league-...`` carries the token ``premodern``, never ``modern``."""
    tokens = set(_TOKEN_RE.findall(path.rsplit("/", 1)[-1].lower()))
    return [fmt for fmt in formats if fmt.lower() in tokens]


@dataclass(frozen=True, slots=True)
class TournamentFile:
    path: str
    blob_sha: str


@dataclass(frozen=True, slots=True)
class ParsedDeck:
    deck_ord: int
    result: str | None
    wins: int
    losses: int
    draws: int
    mainboard: list[dict[str, Any]]
    sideboard: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ParsedRoundMatch:
    round_name: str
    deck_ord_a: int
    deck_ord_b: int
    wins_a: int
    wins_b: int
    draws: int


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    event_id: str          # the file path — already a stable, unique identity
    source: str
    name: str
    event_date: str | None
    format: str | None
    tier: str
    standings_rows: int
    uri: str | None
    blob_sha: str
    decks: list[ParsedDeck] = field(default_factory=list)
    round_matches: list[ParsedRoundMatch] = field(default_factory=list)


class AnswerKind(StrEnum):
    REFUSED = "refused"          # 401, 403, 451
    RATE = "rate"                # 429
    UNAVAILABLE = "unavailable"  # 503
    GENERIC = "generic"          # anything else that ended a run


REFUSAL_STATUSES = frozenset({401, 403, 451})
RATE_STATUS = 429
UNAVAILABLE_STATUS = 503


def answer_kind(http_status: int | None) -> AnswerKind:
    """The kind an HTTP status makes of an answer that ended a run.

    The fetcher decides whether a status ends the run at all: a 404 at an
    mtgo.com month or event page skips the page, and TopDeck's 5xx is "no
    answer for" its format, so neither ever reaches this function.
    """
    if http_status in REFUSAL_STATUSES:
        return AnswerKind.REFUSED
    if http_status == RATE_STATUS:
        return AnswerKind.RATE
    if http_status == UNAVAILABLE_STATUS:
        return AnswerKind.UNAVAILABLE
    return AnswerKind.GENERIC


def answer_reason(exc: BaseException) -> str:
    """An ``Answer.reason``, rendered by the line catalog's rule (plan 14,
    ``lines.md`` §0, "Reasons"): an HTTP status as the code and the server's
    reason phrase, ``HTTP 503 Service Unavailable``; a timeout as ``timed
    out``; anything else as ``str(exc)``.

    A server that sends a status line with no phrase gets the standard one
    for its code, and a code with no standard phrase renders bare
    (``HTTP 599``).
    """
    if isinstance(exc, urllib.error.HTTPError):
        phrase = str(exc.reason or "").strip()
        if not phrase:
            try:
                phrase = HTTPStatus(exc.code).phrase
            except ValueError:
                phrase = ""
        return f"HTTP {exc.code} {phrase}".rstrip()
    # urlopen raises a connect timeout as URLError(reason=TimeoutError) and a
    # read timeout as the bare TimeoutError (socket.timeout is its alias).
    if isinstance(exc, TimeoutError) or (
        isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)
    ):
        return "timed out"
    return str(exc)


@dataclass(frozen=True, slots=True)
class Answer:
    """What a server said that ended a run (plan 14, S3). A run that
    completed has no Answer.

    ``place`` is where the run was when it was answered: for mtgo.com
    ``index``, ``month:YYYY-MM`` or ``event:<slug>``; for TopDeck the format.
    ``retry_after`` is the ``Retry-After`` header as an absolute aware UTC
    time (``holds.parse_retry_after``); ``retry_after_s`` is the seconds
    TopDeck's JSON body asked for (``retryAfterSeconds``), which comes before
    the header. ``first_request`` is whether the run's first request drew the
    answer. ``at`` is when it arrived, an aware UTC time.
    """

    kind: AnswerKind
    reason: str
    at: datetime
    http_status: int | None = None
    place: str | None = None
    retry_after: datetime | None = None
    retry_after_s: float | None = None
    first_request: bool = False

    def __post_init__(self) -> None:
        AnswerKind(self.kind)  # raises ValueError on an unknown kind
        # The hold row's cause is NOT NULL: only a generic answer may lack one.
        if self.kind != AnswerKind.GENERIC and self.http_status is None:
            raise ValueError(f"a {self.kind} answer needs its HTTP status")


@dataclass(frozen=True, slots=True)
class RefreshResult:
    # 'updated' | 'fresh' | 'failed' | 'not_configured' (topdeck.py only —
    # an opt-in source with no credential set, never an error condition) |
    # 'held' (the hold's gate allowed no attempt, metagame/holds.py).
    # When the status is 'updated', ``error`` lists the formats whose query
    # failed, comma-separated (TopDeck only).
    status: str
    commit_sha: str | None = None
    events: int = 0
    skipped: int = 0
    age_seconds: float | None = None
    error: str | None = None
    # The source's meta_fetch_hold row before the run and after it, and the
    # answer that ended the run (None when it completed or never started).
    hold_before: Hold | None = None
    hold_after: Hold | None = None
    answer: Answer | None = None
    by_hand: bool = False
    # TopDeck only: the formats that answered, the ones a 429 or a refusal
    # left unasked, and the ones whose query got no answer (a 5xx, a timeout).
    answered: tuple[str, ...] = ()
    unfetched: tuple[str, ...] = ()
    unanswered: tuple[str, ...] = ()


def fetch_json(url: str, *, timeout: float = TIMEOUT) -> Any:
    """One GET, parsed as JSON. The only two functions that touch the
    network in this module; kept separate from ``fetch_text`` because the
    GitHub API and raw content host want different ``Accept`` headers."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str, *, timeout: float = TIMEOUT) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": HEADERS["User-Agent"]})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # utf-8-sig: tolerate a byte-order mark, same as archetypes/source.py.
        return response.read().decode("utf-8-sig")


def resolve_commit_sha(branch: str = "main") -> str:
    """The repository's current commit, pinned once per refresh so every file
    fetched under it comes from the same snapshot — and stored, so a report
    can name exactly which snapshot it reasoned from (the doc's whole
    reproducibility requirement)."""
    data = fetch_json(f"{API_BASE}/commits/{branch}")
    return data["sha"]


def list_tree(commit_sha: str) -> list[dict[str, Any]]:
    """One recursive listing of the whole repository at a pinned commit —
    the alternative is a directory-listing call per year/month/day, which
    is both slower and rate-limited far more aggressively."""
    data = fetch_json(f"{API_BASE}/git/trees/{commit_sha}?recursive=1")
    if data.get("truncated"):
        # GitHub caps a single tree response; a fallback would page through
        # Tournaments/<source>/<year>/<month>/ with the contents/ endpoint
        # instead. Not implemented: raising here is a loud, honest failure
        # rather than a silent partial refresh, and refresh_metagame's
        # fail-soft handling still keeps whatever was fetched last time.
        raise ValueError("GitHub tree listing was truncated; per-month fallback not implemented")
    return data.get("tree", [])


def fetch_event(commit_sha: str, path: str) -> dict[str, Any]:
    return json.loads(fetch_text(f"{RAW_BASE}/{commit_sha}/{path}"))




def select_paths(
    tree: Sequence[dict[str, Any]],
    *,
    start: date,
    end: date,
    sources: Sequence[str] = SOURCES,
    formats: Sequence[str] = FETCH_FORMATS,
) -> list[TournamentFile]:
    """Which tree entries are worth fetching at all, from the path alone.

    Layout is ``Tournaments/<source>/<year>/<month>/<day>/<event>.json``. The
    date and source are read from the path rather than the file's own
    ``Tournament`` block — reading that would mean fetching every candidate
    just to decide whether to fetch it. A filename without one of ``formats``
    as a whole token is dropped here too (cheaply, before any download);
    ``parse_event`` still cross-checks the file's own ``Tournament.Formats``
    once it is fetched, since a filename is a hint, not a guarantee.
    """
    selected: list[TournamentFile] = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        match = _PATH_RE.match(path)
        if not match:
            continue
        source, year, month, day = match.groups()
        if source not in sources:
            continue
        if not _filename_formats(path, formats):
            continue
        try:
            found = date(int(year), int(month), int(day))
        except ValueError:
            continue
        if not (start <= found <= end):
            continue
        blob_sha = entry.get("sha")
        if not blob_sha:
            continue
        selected.append(TournamentFile(path=path, blob_sha=blob_sha))
    return selected


def already_fetched(conn: sqlite3.Connection) -> dict[str, str]:
    """``path -> blob_sha`` for every event already stored, so a refresh
    only re-fetches a file whose content actually changed upstream.

    Includes twin events too (``duplicate_of IS NOT NULL``): a twin keeps
    its own ``meta_event`` row for exactly this reason (migration 043) — an
    unchanged twin file must never look unfetched and get downloaded again.
    """
    rows = conn.execute("SELECT path, blob_sha FROM meta_event")
    return {row["path"]: row["blob_sha"] for row in rows}




def _parse_record(result: str | None) -> tuple[int, int, int]:
    """``"2-0-0"`` -> ``(2, 0, 0)``. Unparseable or missing degrades to all
    zeros rather than raising — one deck's malformed record must not cost the
    rest of the event."""
    if not result:
        return 0, 0, 0
    parts = str(result).split("-")
    if len(parts) not in (2, 3):
        return 0, 0, 0
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return 0, 0, 0
    while len(numbers) < 3:
        numbers.append(0)
    return numbers[0], numbers[1], numbers[2]


def _standings_records(
    raw: dict[str, Any], player_to_ord: dict[str, int]
) -> dict[int, tuple[int, int, int]]:
    """``deck_ord -> (wins, losses, draws)`` from ``Standings[]``.

    Every real file with standings inspected (2026-08-18) carries a bare
    placement string in ``Decks[].Result`` — ``"1st Place"``, ``"2nd
    Place"`` — never a score; only Tier C (leagues, which never publish
    ``Standings`` at all) uses the ``"N-M"`` form ``_parse_record`` reads.
    ``Standings[].Wins``/``Losses``/``Draws`` are already the structured
    integers, so this is a lookup, not a parse — a malformed row is simply
    absent from the result rather than guessed at (rule 4).
    """
    records: dict[int, tuple[int, int, int]] = {}
    for row in raw.get("Standings") or []:
        if not isinstance(row, dict):
            continue
        ord_ = player_to_ord.get(row.get("Player"))
        if ord_ is None:
            continue
        try:
            records[ord_] = (int(row["Wins"]), int(row["Losses"]), int(row.get("Draws", 0)))
        except (KeyError, TypeError, ValueError):
            continue
    return records


def _card_entries(raw: Any) -> list[dict[str, Any]]:
    """Normalise a Mainboard/Sideboard list to ``[{"count": int, "name": str}]``.

    Casing varies by source (the doc's own finding) — the classic MTGO schema
    ships ``CardName``/``Count``; others ship lowercase. Any entry missing
    both a recognised name key or a valid count is dropped rather than
    guessed at (rule 4): a malformed entry is not a zero-count card.
    """
    entries: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = item.get("CardName") or item.get("card_name") or item.get("Name") or item.get("name")
        count = item.get("Count", item.get("count"))
        if not isinstance(name, str) or not name.strip():
            continue
        try:
            count = int(count)
        except (TypeError, ValueError):
            continue
        entries.append({"count": count, "name": name})
    return entries


def _formats_list(tournament: dict[str, Any]) -> list[str]:
    """``Tournament.Formats`` is a bare string in every real file inspected
    (both MTGO and MTGmelee, verified 2026-08-18: ``"Formats": "Standard"``,
    never a list) — but a list is what the source repository this cache
    forked from ships in other contexts, so both are accepted rather than
    assuming one and silently mis-happens: iterating a bare string
    character-by-character was a real bug caught by running this against
    the live cache, not by the unit tests."""
    raw = tournament.get("Formats")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(f) for f in raw if isinstance(f, str)]
    return []


def _matched_format(
    tournament: dict[str, Any], path: str, formats: Sequence[str]
) -> str | None:
    """Which of ``formats`` this event is, or ``None``. ``Tournament.Formats``
    is the authority, by equality on the lower-cased name (a substring test
    would let ``Premodern`` pass for ``Modern``); the filename decides only
    when the file carries no ``Formats`` at all."""
    canonical = {f.lower(): f for f in FORMATS}
    formats = [canonical.get(f.lower(), f) for f in formats]
    declared = _formats_list(tournament)
    if not declared:
        # Judged against all seven formats, not only the asked ones: a name
        # carrying a format nobody asked for is still ambiguous (rule 4).
        named = _filename_formats(
            path, (*FORMATS, *(f for f in formats if f not in FORMATS))
        )
        if len(named) > 1:
            log.warning("metagame event skipped: its filename names more than one format")
            return None
        if len(named) == 1 and named[0] in formats:
            return named[0]
        return None
    wanted = {f.lower(): f for f in formats}
    for name in declared:
        key = name.strip().lower()
        if key in wanted:
            return wanted[key]
    return None


def parse_event(
    raw: dict[str, Any], file: TournamentFile, formats: Sequence[str] = FETCH_FORMATS
) -> ParsedEvent | None:
    """One cache JSON -> one ``ParsedEvent``, with every ``Player`` name
    resolved to a per-event ordinal and then discarded (see this module's
    docstring). Returns ``None`` when the file is none of ``formats``, or
    is too malformed to use at all — both counted as *skipped*, never fatal
    to the surrounding refresh.
    """
    tournament = raw.get("Tournament") or {}
    matched = _matched_format(tournament, file.path, formats)
    if matched is None:
        return None

    raw_decks = raw.get("Decks") or []
    if not isinstance(raw_decks, list):
        return None

    # Player -> deck_ord first, in its own pass: Standings below resolves
    # against the *complete* mapping, not whatever has been seen so far.
    player_to_ord: dict[str, int] = {}
    for i, raw_deck in enumerate(raw_decks):
        if isinstance(raw_deck, dict) and isinstance(raw_deck.get("Player"), str):
            player_to_ord[raw_deck["Player"]] = i
    standings_records = _standings_records(raw, player_to_ord)

    decks: list[ParsedDeck] = []
    for i, raw_deck in enumerate(raw_decks):
        if not isinstance(raw_deck, dict):
            continue
        # Decks[].Result is a bare placement string ("1st Place") for every
        # tier except C (verified 2026-08-18 against real MTGO and MTGmelee
        # files) — the real per-deck record lives in Standings[] wherever one
        # exists. Falling back to Result only when Standings has nothing for
        # this deck keeps Tier C's real "N-M" record working unchanged.
        wins, losses, draws = standings_records.get(
            i, _parse_record(raw_deck.get("Result"))
        )
        decks.append(
            ParsedDeck(
                deck_ord=i,
                result=raw_deck.get("Result"),
                wins=wins,
                losses=losses,
                draws=draws,
                mainboard=_card_entries(raw_deck.get("Mainboard")),
                sideboard=_card_entries(raw_deck.get("Sideboard")),
            )
        )

    round_matches: list[ParsedRoundMatch] = []
    for rnd in raw.get("Rounds") or []:
        if not isinstance(rnd, dict):
            continue
        round_name = str(rnd.get("RoundName") or "")
        for m in rnd.get("Matches") or []:
            if not isinstance(m, dict):
                continue
            a = player_to_ord.get(m.get("Player1"))
            b = player_to_ord.get(m.get("Player2"))
            if a is None or b is None:
                # A bye, or a player with no matching Decks entry — cannot
                # be expressed as a deck-to-deck matchup, so it is dropped
                # rather than guessed at.
                continue
            wins_a, wins_b, draws = _parse_record(m.get("Result"))
            round_matches.append(ParsedRoundMatch(round_name, a, b, wins_a, wins_b, draws))

    event_source = file.path.split("/", 2)[1] if "/" in file.path else ""
    return ParsedEvent(
        event_id=file.path,
        source=event_source,
        name=str(tournament.get("Name") or file.path.rsplit("/", 1)[-1]),
        event_date=tournament.get("Date"),
        format=matched,
        tier=classify_tier(raw, event_source),
        standings_rows=len(raw.get("Standings") or []),
        uri=tournament.get("Uri"),
        blob_sha=file.blob_sha,
        decks=decks,
        round_matches=round_matches,
    )




_PLACEMENT = re.compile(r"^\s*(\d+)(?:st|nd|rd|th)\s+place\s*$", re.IGNORECASE)


def placement_of(result: str | None) -> int | None:
    """The finishing place a ``Decks[].Result`` names ("1st Place" is 1), or
    None for anything else: a league's "5-0", an empty result."""
    match = _PLACEMENT.match(result or "")
    return int(match[1]) if match else None


def has_lists(event: ParsedEvent) -> bool:
    """Whether any of the event's decks carries a mainboard."""
    return any(d.mainboard for d in event.decks)


def record_read(
    conn: sqlite3.Connection, event_id: str, *, outcome: str, now: str
) -> None:
    """Stamp when an already-stored event was last read, and what came back.

    ``'lists'`` sets ``lists_read_at`` and clears both empty fields;
    ``'empty'`` and ``'gone'`` set ``empty_read_at`` and the kind and keep
    ``lists_read_at``. Updates an existing row only, never inserts, and never
    commits: the caller owns the transaction.
    """
    if outcome not in ("lists", "empty", "gone"):
        raise ValueError(f"unknown read outcome: {outcome!r}")
    if outcome == "lists":
        conn.execute(
            "UPDATE meta_event SET lists_read_at = ?, empty_read_at = NULL, "
            "empty_read_kind = NULL WHERE event_id = ?",
            (now, event_id),
        )
    else:
        conn.execute(
            "UPDATE meta_event SET empty_read_at = ?, empty_read_kind = ? WHERE event_id = ?",
            (now, outcome, event_id),
        )


def store_events(
    conn: sqlite3.Connection, events: Sequence[ParsedEvent], *, now: str | None = None
) -> int:
    """Upsert events, their decklists and their round matches; return how many
    were actually stored.

    Unlike ``archetypes.store_archetypes``, this never deletes by scope
    before inserting: a window-limited refresh must not erase events an
    earlier, wider-windowed refresh already stored. Each event replaces only
    its own prior rows, keyed on ``event_id`` — safe to re-run, like every
    write in this project.

    Each stored event is stamped ``lists_read_at`` or ``empty_read_at`` by
    whether it has decklists. An incoming event with no lists, from any source
    but ``Topdeck``, is declined when the stored copy, or the event it duplicates,
    has lists: a league emptied upstream must not erase decks already read. A declined event gets
    the incoming ``blob_sha`` (so nobody downloads the same empty copy again)
    and an ``'empty'`` stamp, keeps its decks, twins and ``duplicate_of``, and
    is not counted. Callers add ``len(events) - stored`` to ``skipped``.

    Does not call ``mark_duplicate_events`` (``metagame/dedup.py``) itself —
    ``cmd_meta`` calls it once, after every refresh in this batch has landed,
    so a twin fetched earlier in the same refresh is judged against its
    final content rather than a stale mid-batch state.
    """
    events = list(events)
    if not events:
        return 0
    stamp = now or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    stored = 0
    conn.execute("BEGIN")
    try:
        for event in events:
            lists = has_lists(event)
            # The stored copy "has lists" itself, or is a twin (dedup removed
            # its decks) of an event that does.
            if not lists and event.source != "Topdeck" and conn.execute(
                "SELECT EXISTS (SELECT 1 FROM meta_deck WHERE mainboard_json != '[]' "
                "AND event_id IN (?, (SELECT duplicate_of FROM meta_event WHERE event_id = ?)))",
                (event.event_id, event.event_id),
            ).fetchone()[0]:
                log.warning(
                    "metagame event %s came back without decklists; keeping the stored ones",
                    event.event_id,
                )
                conn.execute(
                    "UPDATE meta_event SET blob_sha = ? WHERE event_id = ?",
                    (event.blob_sha, event.event_id),
                )
                record_read(conn, event.event_id, outcome="empty", now=stamp)
                continue
            conn.execute("DELETE FROM meta_round_match WHERE event_id = ?", (event.event_id,))
            conn.execute("DELETE FROM meta_deck WHERE event_id = ?", (event.event_id,))
            conn.execute(
                """
                INSERT INTO meta_event
                     (event_id, path, blob_sha, source, name, event_date, format, tier,
                      standings_rows, uri)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (event_id) DO UPDATE SET
                     path = excluded.path, blob_sha = excluded.blob_sha,
                     source = excluded.source, name = excluded.name,
                     event_date = excluded.event_date, format = excluded.format,
                     tier = excluded.tier, standings_rows = excluded.standings_rows,
                     uri = excluded.uri, duplicate_of = NULL
                """,
                (event.event_id, event.event_id, event.blob_sha, event.source, event.name,
                 event.event_date, event.format, event.tier, event.standings_rows, event.uri),
            )
            # A re-fetched file is judged afresh: clear duplicate_of so
            # mark_duplicate_events (metagame/dedup.py) re-derives whether it
            # is still a twin of anything, rather than trusting a verdict
            # reached over content that may no longer be there.
            #
            # If this event is itself a survivor, its own twins were judged
            # against content that this store now replaces. Clearing their
            # blob_sha makes refresh_metagame see them as changed on the next
            # refresh, so they get re-fetched and judged against the new
            # content too, instead of quietly going stale behind a survivor
            # that moved on without them.
            conn.execute(
                "UPDATE meta_event SET blob_sha = '' WHERE duplicate_of = ?", (event.event_id,)
            )
            conn.executemany(
                """
                INSERT INTO meta_deck
                     (event_id, deck_ord, result, wins, losses, draws,
                      mainboard_json, sideboard_json)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (event.event_id, d.deck_ord, d.result, d.wins, d.losses, d.draws,
                     json.dumps(d.mainboard, separators=(",", ":")),
                     json.dumps(d.sideboard, separators=(",", ":")))
                    for d in event.decks
                ],
            )
            conn.executemany(
                """
                INSERT INTO meta_round_match
                     (event_id, round_name, deck_ord_a, deck_ord_b, wins_a, wins_b, draws)
                     VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (event.event_id, rm.round_name, rm.deck_ord_a, rm.deck_ord_b,
                     rm.wins_a, rm.wins_b, rm.draws)
                    for rm in event.round_matches
                ],
            )
            record_read(
                conn, event.event_id, outcome="lists" if lists else "empty", now=stamp
            )
            stored += 1
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return stored


def _age_from_timestamp(fetched_at: str | None) -> float | None:
    if not fetched_at:
        return None
    try:
        fetched = datetime.strptime(fetched_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return (datetime.now(UTC) - fetched).total_seconds()


def cache_age_seconds(conn: sqlite3.Connection, *, source: str | None = None) -> float | None:
    """Staleness of one corpus source, or — unscoped — the *oldest* (most
    stale) of every source that has ever been fetched, so a status tile
    reporting one scalar cannot hide a source that hasn't refreshed in weeks
    behind a source that refreshed a minute ago. A source with no row (never
    configured, or never successfully fetched) simply doesn't count towards
    "oldest" — it is reported separately as "never fetched", not as
    infinitely stale.

    Unscoped, a database with no ``meta_fetch_source`` row at all falls back
    to ``meta_fetch``'s singleton. ``source="fbettega"`` reads
    ``meta_fetch_source``, which ``refresh_metagame`` below keeps in sync
    with ``meta_fetch``, and is what that refresh judges its own freshness
    by: never the unscoped oldest, which another source's stamp decides.
    """
    if source is not None:
        row = conn.execute(
            "SELECT fetched_at FROM meta_fetch_source WHERE source = ?", (source,)
        ).fetchone()
        return _age_from_timestamp(row["fetched_at"] if row else None)

    ages = [
        age
        for (fetched_at,) in conn.execute("SELECT fetched_at FROM meta_fetch_source")
        if (age := _age_from_timestamp(fetched_at)) is not None
    ]
    if ages:
        return max(ages)

    # No per-source rows at all (a database that predates migration 022's
    # backfill, or one that has never run a refresh) — fall back to the
    # legacy singleton row so an existing cache still reports its real age.
    row = conn.execute("SELECT fetched_at FROM meta_fetch WHERE id = 1").fetchone()
    return _age_from_timestamp(row["fetched_at"] if row else None)


MAX_AGE_SECONDS = 24 * 3600


def refresh_metagame(
    conn: sqlite3.Connection,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_age_seconds: float = MAX_AGE_SECONDS,
    force: bool = False,
    sources: Sequence[str] = SOURCES,
    formats: Sequence[str] = FETCH_FORMATS,
) -> RefreshResult:
    """Update the tournament corpus if it is stale. Never raises.

    Stale means fbettega's own stamp, ``cache_age_seconds(conn,
    source="fbettega")``, is older than ``max_age_seconds`` or absent.
    Unscoped, that function is the oldest of every source, and a stale or
    paused TopDeck sent this refresh to GitHub on every attempt (plan 14,
    defect 1).

    Same fail-soft contract as ``archetypes.refresh_archetypes``: an offline
    machine keeps whatever it fetched last time, and a first run with no
    cache leaves the metagame layer empty until the next attempt succeeds.
    """
    age = cache_age_seconds(conn, source="fbettega")
    if not force and age is not None and age < max_age_seconds:
        return RefreshResult(status="fresh", age_seconds=age)

    end = datetime.now(UTC).date()
    start = end - timedelta(days=window_days)

    try:
        commit_sha = resolve_commit_sha()
        tree = list_tree(commit_sha)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, KeyError) as exc:
        log.warning("metagame refresh failed, keeping the cached copy: %s", exc)
        return RefreshResult(status="failed", age_seconds=age, error=str(exc))

    candidates = select_paths(tree, start=start, end=end, sources=sources, formats=formats)
    known = already_fetched(conn)
    changed = [f for f in candidates if known.get(f.path) != f.blob_sha]
    # Over the ceiling, the newest files are kept (the path starts with the
    # source, then year/month/day) and the overflow is counted as skipped.
    changed.sort(key=lambda f: tuple(int(p) for p in f.path.split("/")[2:5]), reverse=True)
    to_fetch = changed[:MAX_FILES_PER_REFRESH]
    overflow = len(changed) - len(to_fetch)
    if overflow:
        log.warning("metagame refresh: %d files over the ceiling, newest kept", overflow)

    events: list[ParsedEvent] = []
    skipped = overflow
    for file in to_fetch:
        try:
            raw = fetch_event(commit_sha, file.path)
            parsed = parse_event(raw, file, formats)
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            log.warning("skipping metagame event %s: %s", file.path, exc)
            skipped += 1
            continue
        if parsed is None:
            skipped += 1
            continue
        events.append(parsed)

    stored = store_events(conn, events)
    skipped += len(events) - stored
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute("BEGIN")
    try:
        conn.execute(
            """
            INSERT INTO meta_fetch (id, commit_sha, fetched_at, window_days, events, skipped)
                 VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                 commit_sha = excluded.commit_sha, fetched_at = excluded.fetched_at,
                 window_days = excluded.window_days, events = excluded.events,
                 skipped = excluded.skipped
            """,
            (commit_sha, fetched_at, window_days, stored, skipped),
        )
        # Mirrored into the per-source table (022_meta_source_fetch.sql) so
        # cache_age_seconds(conn) unscoped can report every source's
        # freshness from one place, without meta_fetch's own reproducibility
        # story (a pinned commit_sha) losing its dedicated row.
        conn.execute(
            """
            INSERT INTO meta_fetch_source (source, ref, fetched_at, window_days, events, skipped)
                 VALUES ('fbettega', ?, ?, ?, ?, ?)
            ON CONFLICT (source) DO UPDATE SET
                 ref = excluded.ref, fetched_at = excluded.fetched_at,
                 window_days = excluded.window_days, events = excluded.events,
                 skipped = excluded.skipped
            """,
            (commit_sha, fetched_at, window_days, stored, skipped),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return RefreshResult(
        status="updated", commit_sha=commit_sha, events=stored,
        skipped=skipped, age_seconds=age,
    )
