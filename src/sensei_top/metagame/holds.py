"""The hold a corpus fetcher keeps on a source that answered with something
other than its pages (plan 14, S3): one ``meta_fetch_hold`` row per source,
``mtgo`` or ``topdeck``, written by ``apply_outcome`` and read by ``gate``.

A hold is ``waiting`` (a 429 or a 503 asked the fetcher to come back later,
and ``not_before`` says when) or ``paused`` (a refusal, a second 429 in a row,
or a day of 503s; only a hand run of ``sensei-top meta`` tries again).

Traps this module exists to avoid:

1. **Nothing shortens a hold.** ``gate`` takes no ``force`` and no format:
   ``--force`` and ``--format`` override the freshness rule, which the
   fetcher applies after the gate, never the hold.
2. **A time the server named is never breached.** mtgo.com's not-befores are
   rounded up to the minute (``ceil_min``) because the lines print minutes;
   TopDeck's is its own time, rounded up to the second and never raised to a
   floor (D18). Rounding down would let a run start before the server's time.
3. **Only first-request 503s count towards the pause.** A challenge page meant
   for browsers answers the very first request, run after run; an index that
   opens and a later page that does not is an outage behind a working front,
   and restarts the count (k1).
4. **A generic answer changes nothing.** A timeout, another status or no
   connection leaves the row exactly as it was, including ``last_status``:
   it says nothing about the site's pace, so it neither ends a wait nor
   breaks a streak of 429s (Q13.5).
5. **A refusal pauses from the moment it arrives** (k4), and a pause keeps
   the date it began through every later answer (Q13.3); only its cause, and
   a 429's or 503's not-before, move (k3).

Times are aware UTC datetimes here and ``%Y-%m-%dT%H:%M:%SZ`` in SQLite, so a
``Hold`` that ``apply_outcome`` returns equals the one ``read_hold`` reads
back. Only the fetchers call into this module; ``project()`` never reads the
table.
"""

from __future__ import annotations

import email.utils
import logging
import math
import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from sensei_top.metagame.source import RATE_STATUS, UNAVAILABLE_STATUS, Answer, AnswerKind

log = logging.getLogger(__name__)

MTGO = "mtgo"
TOPDECK = "topdeck"
SOURCES = (MTGO, TOPDECK)

TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# mtgo.com: a first 429 waits at least three hours, a 503 at least one; the
# hour also keeps first-request 503s at least an hour apart (k2).
_MTGO_RATE_WAIT = timedelta(hours=3)
_MTGO_UNAVAILABLE_WAIT = timedelta(hours=1)
# A 429 with no Retry-After, once the source is paused or a second time in a
# row; and TopDeck's 429 when it names no time of its own.
_DEFAULT_RATE_WAIT = timedelta(hours=1)
# The day rule (Q13.4, k2): three or more first-request 503s, 24 h after the
# first of them, pause mtgo.com.
_DAY_OF_503S_ANSWERS = 3
_DAY_OF_503S_SPAN = timedelta(hours=24)


class HoldStatus(StrEnum):
    WAITING = "waiting"
    PAUSED = "paused"


class Gate(StrEnum):
    """What a fetcher may do, given its source's hold."""

    FRESHNESS = "freshness"  # run when the freshness rule (or --force) says so
    RUN = "run"              # one ordinary run, whatever the freshness rule says
    HELD = "held"            # no attempt; the result's status is 'held'


@dataclass(frozen=True, slots=True)
class Hold:
    """One ``meta_fetch_hold`` row. ``http_status`` is the hold's cause;
    ``answers`` counts the current run of first-request 503s (mtgo.com only,
    0 otherwise); ``last_status`` and ``last_at`` are the latest answer that
    affected the hold."""

    source: str
    status: HoldStatus
    http_status: int
    answers: int
    since: datetime
    last_status: int
    last_at: datetime
    not_before: datetime | None


def ceil_min(t: datetime) -> datetime:
    """``t`` rounded up to the minute; a time already on the minute is kept."""
    floor = t.replace(second=0, microsecond=0)
    return floor if floor == t else floor + timedelta(minutes=1)


def _ceil_sec(t: datetime) -> datetime:
    floor = t.replace(microsecond=0)
    return floor if floor == t else floor + timedelta(seconds=1)


def _floor_sec(t: datetime) -> datetime:
    return t.replace(microsecond=0)


def _format(t: datetime) -> str:
    return t.astimezone(UTC).strftime(TIME_FORMAT)


def _parse(text: str) -> datetime:
    return datetime.strptime(text, TIME_FORMAT).replace(tzinfo=UTC)


def parse_retry_after(value: str | None, *, at: datetime) -> datetime | None:
    """A ``Retry-After`` header as an absolute aware UTC time.

    The header is delta-seconds (counted from ``at``, when the response
    arrived) or an HTTP-date. Absent or blank gives None; anything else that
    is neither form counts as absent too, with a warning — never a guessed
    time.
    """
    if value is None or not value.strip():
        return None
    text = value.strip()
    try:
        if text.isascii() and text.isdigit():
            return at + timedelta(seconds=int(text))
        parsed = email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError, OverflowError):
        log.warning("unparsable Retry-After %r, treated as absent", text)
        return None
    # An HTTP-date is always GMT; parsedate_to_datetime returns a naive time
    # for a "-0000" zone, which says the same.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def read_hold(conn: sqlite3.Connection, source: str) -> Hold | None:
    """The source's hold, or None when it has none."""
    row = conn.execute(
        "SELECT status, http_status, answers, since, last_status, last_at, not_before "
        "FROM meta_fetch_hold WHERE source = ?",
        (source,),
    ).fetchone()
    if row is None:
        return None
    status, http_status, answers, since, last_status, last_at, not_before = row
    return Hold(
        source=source,
        status=HoldStatus(status),
        http_status=http_status,
        answers=answers,
        since=_parse(since),
        last_status=last_status,
        last_at=_parse(last_at),
        not_before=_parse(not_before) if not_before is not None else None,
    )


def _ahead(hold: Hold, now: datetime) -> bool:
    return hold.not_before is not None and hold.not_before > now


def gate(hold: Hold | None, *, now: datetime, by_hand: bool) -> Gate:
    """Whether a fetch may be attempted (plan 14, S3, "The gate").

    No hold, or a wait whose not-before has passed: the freshness rule
    decides, for the loop and a hand run alike. A wait still ahead, or a pause
    with a not-before still ahead: no attempt. A pause otherwise: the loop
    makes no attempt, a hand run makes one ordinary run.
    """
    if hold is None:
        return Gate.FRESHNESS
    if hold.status == HoldStatus.WAITING:
        return Gate.HELD if _ahead(hold, now) else Gate.FRESHNESS
    if _ahead(hold, now) or not by_hand:
        return Gate.HELD
    return Gate.RUN


def visible(hold: Hold | None, now: datetime) -> bool:
    """Whether the hold stands: paused, or waiting with a not-before ahead."""
    if hold is None:
        return False
    return hold.status == HoldStatus.PAUSED or _ahead(hold, now)


def _write(conn: sqlite3.Connection, hold: Hold) -> None:
    conn.execute(
        """
        INSERT INTO meta_fetch_hold
             (source, status, http_status, answers, since, last_status, last_at, not_before)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source) DO UPDATE SET
             status = excluded.status, http_status = excluded.http_status,
             answers = excluded.answers, since = excluded.since,
             last_status = excluded.last_status, last_at = excluded.last_at,
             not_before = excluded.not_before
        """,
        (
            hold.source, str(hold.status), hold.http_status, hold.answers, _format(hold.since),
            hold.last_status, _format(hold.last_at),
            _format(hold.not_before) if hold.not_before is not None else None,
        ),
    )


def _refused(source: str, before: Hold | None, answer: Answer, now: datetime) -> Hold:
    # From none or a wait, the pause begins now (k4); from a pause, the cause
    # is replaced and the date kept (Q13.3). Either way no not-before: a
    # refusal names no time.
    since = before.since if before is not None and before.status == HoldStatus.PAUSED else now
    assert answer.http_status is not None
    return Hold(
        source=source, status=HoldStatus.PAUSED, http_status=answer.http_status, answers=0,
        since=since, last_status=answer.http_status, last_at=now, not_before=None,
    )


def _mtgo_rate(before: Hold | None, answer: Answer, now: datetime) -> Hold:
    ra = answer.retry_after
    if before is not None and before.status == HoldStatus.PAUSED:
        status, cause, answers, since = (
            before.status, before.http_status, before.answers, before.since
        )
        not_before = ceil_min(ra if ra is not None else now + _DEFAULT_RATE_WAIT)
    elif before is not None and before.http_status == RATE_STATUS:
        # The second 429 in a row, wherever in the run it came (Q13.5).
        status, cause, answers, since = HoldStatus.PAUSED, RATE_STATUS, 0, now
        not_before = ceil_min(ra if ra is not None else now + _DEFAULT_RATE_WAIT)
    else:
        # None, or a wait on a 503: a 429 starts its own wait.
        status, cause, answers, since = HoldStatus.WAITING, RATE_STATUS, 0, now
        floor = now + _MTGO_RATE_WAIT
        not_before = ceil_min(max(ra, floor) if ra is not None else floor)
    return Hold(
        source=MTGO, status=status, http_status=cause, answers=answers, since=since,
        last_status=RATE_STATUS, last_at=now, not_before=not_before,
    )


def _mtgo_unavailable(
    before: Hold | None, answer: Answer, *, page_read: bool, now: datetime
) -> Hold:
    ra = answer.retry_after
    counted = answer.first_request and not page_read
    if before is not None and before.status == HoldStatus.PAUSED:
        # The pause keeps its cause and date; a 503 sets the not-before only
        # when it names one (k3).
        return Hold(
            source=MTGO, status=before.status, http_status=before.http_status,
            answers=before.answers, since=before.since, last_status=UNAVAILABLE_STATUS,
            last_at=now, not_before=ceil_min(ra) if ra is not None else None,
        )
    floor = now + _MTGO_UNAVAILABLE_WAIT
    not_before = ceil_min(max(ra, floor) if ra is not None else floor)
    if before is None or before.http_status != UNAVAILABLE_STATUS:
        # None, or a wait on a 429: a 503 starts a different wait (Q13.5).
        return Hold(
            source=MTGO, status=HoldStatus.WAITING, http_status=UNAVAILABLE_STATUS,
            answers=1 if counted else 0, since=now, last_status=UNAVAILABLE_STATUS,
            last_at=now, not_before=not_before,
        )
    answers, since = before.answers, before.since
    if page_read:
        answers = 0  # k1: a page read before the 503 restarts the count
    elif counted:
        if answers == 0:
            since = now
        answers += 1
    if answers >= _DAY_OF_503S_ANSWERS and now - since >= _DAY_OF_503S_SPAN:
        return Hold(
            source=MTGO, status=HoldStatus.PAUSED, http_status=UNAVAILABLE_STATUS,
            answers=answers, since=now, last_status=UNAVAILABLE_STATUS, last_at=now,
            not_before=ceil_min(ra) if ra is not None else None,
        )
    return Hold(
        source=MTGO, status=HoldStatus.WAITING, http_status=UNAVAILABLE_STATUS,
        answers=answers, since=since, last_status=UNAVAILABLE_STATUS, last_at=now,
        not_before=not_before,
    )


def _topdeck_not_before(answer: Answer, now: datetime) -> datetime:
    # retryAfterSeconds, else the header, else an hour: TopDeck's own time,
    # to the second, with no floor (D18). The body's seconds count from the
    # response, not from whenever this runs.
    if answer.retry_after_s is not None:
        try:
            return _ceil_sec(answer.at + timedelta(seconds=math.ceil(answer.retry_after_s)))
        except (ValueError, OverflowError):
            log.warning(
                "unusable retryAfterSeconds %r, falling back", answer.retry_after_s
            )
    if answer.retry_after is not None:
        return _ceil_sec(answer.retry_after)
    return _ceil_sec(now + _DEFAULT_RATE_WAIT)


def _topdeck_rate(before: Hold | None, answer: Answer, now: datetime) -> Hold:
    not_before = _topdeck_not_before(answer, now)
    if before is None:
        status, cause, since = HoldStatus.WAITING, RATE_STATUS, now
    elif before.status == HoldStatus.WAITING:
        status, cause, since = HoldStatus.PAUSED, RATE_STATUS, now
    else:
        status, cause, since = before.status, before.http_status, before.since
    return Hold(
        source=TOPDECK, status=status, http_status=cause, answers=0, since=since,
        last_status=RATE_STATUS, last_at=now, not_before=not_before,
    )


def apply_outcome(
    conn: sqlite3.Connection,
    source: str,
    *,
    before: Hold | None,
    answer: Answer | None,
    page_read: bool,
    completed: bool,
    now: datetime,
) -> Hold | None:
    """Write the hold a run leaves behind, and return it (plan 14, S3,
    "mtgo's transitions" and "TopDeck's transitions").

    ``before`` is the hold the run started under (``read_hold``), ``answer``
    what ended it, ``page_read`` whether any page opened before the answer
    (mtgo.com: the index counts), ``completed`` whether the run finished its
    work; ``now`` is an aware UTC time.

    A completed run deletes the row; it is the caller's to stamp
    ``meta_fetch_source`` with it. A generic answer, or a run that neither
    completed nor drew an answer (the gate held it), leaves the row as it
    was. Every other answer writes the row, ``last_status`` and ``last_at``
    included. One statement at most, and never a commit: inside the caller's
    transaction it joins it.
    """
    if source not in SOURCES:
        raise ValueError(f"no hold rules for source {source!r}")
    if answer is not None and completed:
        raise ValueError("a run that drew an answer did not complete")
    if answer is None:
        if completed:
            conn.execute("DELETE FROM meta_fetch_hold WHERE source = ?", (source,))
            return None
        return before
    if answer.kind == AnswerKind.GENERIC:
        return before

    if answer.kind == AnswerKind.REFUSED:
        after = _refused(source, before, answer, now)
    elif source == MTGO and answer.kind == AnswerKind.RATE:
        after = _mtgo_rate(before, answer, now)
    elif source == MTGO:
        after = _mtgo_unavailable(before, answer, page_read=page_read, now=now)
    elif answer.kind == AnswerKind.RATE:
        after = _topdeck_rate(before, answer, now)
    else:
        # TopDeck's 5xx is "no answer for" its format, never an Answer.
        raise ValueError("TopDeck takes no 503 hold")
    # Stored to the second, so the Hold returned is the one read_hold reads
    # back. Not-befores are already rounded up; these two round down.
    after = replace(after, since=_floor_sec(after.since), last_at=_floor_sec(after.last_at))
    _write(conn, after)
    return after
