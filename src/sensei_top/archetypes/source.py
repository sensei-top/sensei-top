"""Archetype definitions from MTGOFormatData — the project's second download.

Arena tells us nothing about the opponent's deck, so naming it means matching
the cards they revealed against a list of what decks exist. That list has to
come from somewhere, and this module is the only place that fetches it. Like
``cards.py`` it only ever downloads: a bare GET with a User-Agent, no query
string, no body, nothing about a match leaving the machine.

The definitions are rules, not decklists — "an Azorius Momo deck plays Momo,
Friendly Flier and at least one of Haliya or Abandoned Air Temple, and never
plays Jeskai Revelation" — which is what makes them usable against the handful
of cards a game actually reveals. ``classify.py`` owns that evaluation.

Failure is never fatal here. A refresh that cannot reach GitHub keeps the
cached copy and says how old it is; a single malformed file upstream is skipped
and counted rather than costing the whole fetch.
"""

from __future__ import annotations

import io
import json
import logging
import re
import sqlite3
import tarfile
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

# The whole repository in one request. The alternative is ~70 requests for
# Standard alone, each with its own TLS handshake, plus a rate-limited API call
# just to list the directory. The archive is ~350 KB.
ARCHIVE_URL = "https://codeload.github.com/Badaro/MTGOFormatData/tar.gz/refs/heads/main"

# Badaro's own sibling repositories (MTGODecklistCache, MTGOArchetypeParser)
# were both archived in 2025; MTGOFormatData itself is not, and is actively
# maintained by Jiliac for Standard/Pioneer/Modern/Legacy/Pauper — but the
# same owner having archived two of three related repos is exactly the
# situation a fallback exists for. Jiliac's own fork is the standing mirror:
# tried only when the primary host fails outright, never preferred over it.
FALLBACK_ARCHIVE_URL = "https://codeload.github.com/Jiliac/MTGOFormatData/tar.gz/refs/heads/main"

HEADERS = {"User-Agent": "sensei-top/0.1", "Accept": "application/gzip"}
TIMEOUT = 30.0

# The six formats MTGOFormatData ships rules for (Premodern has none, and gets
# a colours-and-signature-card label instead). Only each format's live folder
# loads: the folder name is matched exactly, so a retired Standard season never
# comes in.
FORMATS: tuple[str, ...] = ("Standard", "Pioneer", "Modern", "Legacy", "Vintage", "Pauper")

MAX_AGE_SECONDS = 24 * 3600

# Five files upstream carry a trailing comma, which is not legal JSON. A regex
# is cheaper than a JSON5 dependency for one deviation.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


@dataclass(frozen=True, slots=True)
class ArchetypeFile:
    format: str
    kind: str          # 'archetype' | 'fallback'
    source: str        # the file stem, and the identity: upstream names repeat
    name: str
    include_color: bool
    definition: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RefreshResult:
    status: str                  # 'updated' | 'fresh' | 'failed'
    files: int = 0
    skipped: int = 0
    age_seconds: float | None = None
    error: str | None = None


def loads_tolerant(text: str) -> Any:
    """``json.loads``, forgiving the one deviation upstream actually ships."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_TRAILING_COMMA.sub(r"\1", text))


def fetch_archive(url: str = ARCHIVE_URL, *, timeout: float = TIMEOUT) -> bytes:
    """Download the definitions archive. The only networked function."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _kind_of(parts: Sequence[str], fmt: str) -> str | None:
    """Classify a member path, matching the format folder *exactly*.

    Upstream keeps retired seasons beside the live one — ``Standard`` and
    ``Standard-20240803-20250730`` are siblings — so a prefix match would load
    a rotated-out metagame on top of the current one.
    """
    for index, part in enumerate(parts[:-2]):
        if part != "Formats" or parts[index + 1] != fmt:
            continue
        folder = parts[index + 2]
        if folder == "Archetypes":
            return "archetype"
        if folder == "Fallbacks":
            return "fallback"
    return None


def read_archive(
    blob: bytes, formats: Sequence[str] = FORMATS
) -> tuple[list[ArchetypeFile], int]:
    """Extract the definitions we care about. Returns ``(files, skipped)``."""
    found: list[ArchetypeFile] = []
    skipped = 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".json"):
                continue
            parts = member.name.split("/")
            for fmt in formats:
                kind = _kind_of(parts, fmt)
                if kind is None:
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    skipped += 1
                    break
                try:
                    # utf-8-sig: some files carry a byte-order mark.
                    definition = loads_tolerant(handle.read().decode("utf-8-sig"))
                    name = definition["Name"]
                except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    # One bad file upstream must not cost the whole refresh.
                    log.warning("skipping archetype file %s: %s", member.name, exc)
                    skipped += 1
                    break
                found.append(
                    ArchetypeFile(
                        format=fmt,
                        kind=kind,
                        source=parts[-1].removesuffix(".json"),
                        name=name,
                        include_color=bool(definition.get("IncludeColorInName")),
                        definition=definition,
                    )
                )
                break
    return found, skipped


def store_archetypes(
    conn: sqlite3.Connection, files: Iterable[ArchetypeFile], *, url: str = ARCHIVE_URL
) -> int:
    """Replace the cached definitions for whichever formats were fetched."""
    files = list(files)
    fetched_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    formats = sorted({f.format for f in files})
    placeholders = ",".join("?" for _ in formats)

    conn.execute("BEGIN")
    try:
        if formats:
            conn.execute(f"DELETE FROM archetypes WHERE format IN ({placeholders})", formats)
        conn.executemany(
            """
            INSERT INTO archetypes
                 (format, kind, source, name, include_color, definition, fetched_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (f.format, f.kind, f.source, f.name, int(f.include_color),
                 json.dumps(f.definition, separators=(",", ":")), fetched_at)
                for f in files
            ],
        )
        conn.execute(
            """
            INSERT INTO archetype_fetch (id, url, fetched_at, files, skipped)
                 VALUES (1, ?, ?, ?, 0)
            ON CONFLICT (id) DO UPDATE SET
                 url = excluded.url, fetched_at = excluded.fetched_at, files = excluded.files
            """,
            (url, fetched_at, len(files)),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(files)


def cache_age_seconds(conn: sqlite3.Connection) -> float | None:
    """Seconds since the last successful fetch, or None if there never was one."""
    row = conn.execute("SELECT fetched_at FROM archetype_fetch WHERE id = 1").fetchone()
    if row is None or not row[0]:
        return None
    try:
        fetched = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return (datetime.now(UTC) - fetched).total_seconds()


def refresh_archetypes(
    conn: sqlite3.Connection,
    *,
    max_age_seconds: float = MAX_AGE_SECONDS,
    force: bool = False,
    url: str = ARCHIVE_URL,
    fallback_url: str | None = FALLBACK_ARCHIVE_URL,
) -> RefreshResult:
    """Update the cached definitions if they are stale. Never raises.

    Called at ``serve`` start, where a missing network must cost nothing: an
    offline machine keeps whatever it fetched last time, and a first run with
    no cache at all simply leaves every opponent unclassified until the next
    attempt succeeds.

    ``fallback_url`` is tried only when ``url`` fails outright, and only when
    ``url`` is the default ``ARCHIVE_URL`` — a caller who explicitly asked for
    a specific archive gets exactly that archive or a clean failure, never a
    silent substitution. Pass ``fallback_url=None`` to disable it entirely.
    """
    age = cache_age_seconds(conn)
    if not force and age is not None and age < max_age_seconds:
        return RefreshResult(status="fresh", age_seconds=age)

    try_fallback = fallback_url is not None and url == ARCHIVE_URL
    used_url = url
    try:
        files, skipped = read_archive(fetch_archive(url))
    except (urllib.error.URLError, TimeoutError, tarfile.TarError, OSError, ValueError) as exc:
        if not try_fallback:
            log.warning("archetype refresh failed, keeping the cached copy: %s", exc)
            return RefreshResult(status="failed", age_seconds=age, error=str(exc))
        log.warning(
            "archetype refresh from %s failed (%s), trying fallback %s", url, exc, fallback_url
        )
        used_url = fallback_url  # type: ignore[assignment]
        try:
            files, skipped = read_archive(fetch_archive(used_url))
        except (
            urllib.error.URLError, TimeoutError, tarfile.TarError, OSError, ValueError,
        ) as fallback_exc:
            log.warning("archetype refresh failed, keeping the cached copy: %s", fallback_exc)
            return RefreshResult(status="failed", age_seconds=age, error=str(fallback_exc))

    if not files:
        # Upstream renames its format folder when a season rotates. Replacing a
        # working cache with nothing would be strictly worse than being stale.
        message = "archive contained no definitions for the configured formats"
        log.warning("archetype refresh failed, keeping the cached copy: %s", message)
        return RefreshResult(status="failed", age_seconds=age, error=message)

    store_archetypes(conn, files, url=used_url)
    conn.execute("UPDATE archetype_fetch SET skipped = ? WHERE id = 1", (skipped,))
    return RefreshResult(status="updated", files=len(files), skipped=skipped, age_seconds=age)
