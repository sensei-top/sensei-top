"""Log entry segmentation for Arena's Player.log.

Seven entry shapes matter and everything else is engine noise; each is
described in docs/arena-log.md, "Entry shapes". Shapes 1-5 are verified
against a real 2026.62 log (Steam/Proton, Linux host), 6 against a real
draft capture; 7 has never been captured:

1. Single-line request: ``[UnityCrossThreadLogger]==> Method {json}``.
2. Response: a bare ``<== Method(uuid)`` line, usually right after a header
   line, then the payload from the next line on.
3. Prefixed event with header, payload on the following line(s).
4. Bare JSON with no header at all.
5. Response with a non-JSON body (``DeckDeleteDeck``'s ``Success``).
6. Labeled inline event: ``[UnityCrossThreadLogger]Draft.Notify {json}``.
7. Summarized message: a ``[Message summarized because …]`` block, warned
   once and never stored.

JSON payloads are extracted by brace-depth counting that respects string
literals and backslash escapes: payloads legitimately contain ``{``/``}``
inside strings (card text, escaped nested JSON), so naive counting corrupts.

What a header is, and why every header replaces the last one's time even
when its own can't be read, is in docs/arena-log.md, "Timestamps". Parsing
never decides which field of a slash or dot stamp is the month: a
*resolver* (``DateResolver``) does, one call per header, in file order.
``locale_hint`` is the shorthand for the fixed one (``fixed_resolver``); a
year-first stamp reads as written under any. Unknown or impossible means
``logged_at`` is ``None``, never synthesized (non-negotiable #4).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

log = logging.getLogger(__name__)

UNITY_PREFIX = "[UnityCrossThreadLogger]"
_NOISE_PREFIXES = ("[PhysX]", "[Manifest]", "[TaskLogger]", "[Subsystems]", "[SocialManager]")

_REQUEST_RE = re.compile(r"^==>\s+(?P<method>\S+)\s+(?P<json>\{.*)$")
_RESPONSE_RE = re.compile(r"^<==\s+(?P<method>[^(\s]+)\((?P<uuid>[^)]*)\)\s*$")
# A prefixed line that is its own label plus an inline payload:
#   [UnityCrossThreadLogger]Draft.Notify {"draftId":...}
# Purely structural — the reader never learns what any label *means*
# (AGENTS.md non-negotiable #1); it just stops discarding the payload.
# Anchored on a leading letter so header timestamps ("9/8/2026 8:01:17 PM")
# can never match this instead.
_LABELED_EVENT_RE = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9._]*)\s+(?P<json>\{.*)$")
# Header detection only: a digit-led body with a time before its first ": ".
# Whether the stamp is in a known shape is _SHAPES' question, not this one's.
_DIGIT_RE = re.compile(r"\d", re.ASCII)
_HEADER_TIME_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}", re.ASCII)

DATE_ORDERS = ("mdy", "dmy")

_TIME = r"(?P<hour>\d{1,2}):(?P<min>\d{2}):(?P<sec>\d{2})"
_SLASH_DATE = r"(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<year>\d{4})\s+"
# 오전 (AM) is in no capture; accepted by symmetry with the captured 오후.
# Every other designator is the captured English pair.
_PM_DESIGNATORS = frozenset({"PM", "오후"})


class EntryKind(StrEnum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"


@dataclass(frozen=True, slots=True)
class LogEntry:
    kind: EntryKind
    payload: str                    # raw JSON text exactly as extracted
    label: str | None = None        # method name (requests/responses) or header context
    logged_at: str | None = None    # ISO-8601, naive local time from header; None if unknown
    line_number: int = 0            # 1-based line where the payload started
    header: str | None = None       # stamp logged_at came from, as written; None if no header


@dataclass(frozen=True, slots=True)
class _Shape:
    key: str
    pattern: re.Pattern[str]
    year_first: bool


def _shape(key: str, pattern: str, *, year_first: bool = False) -> _Shape:
    return _Shape(key, re.compile(pattern, re.ASCII), year_first)


# Every stamp shape a real client has written (tests/fixtures/
# header_languages.log, header_relaunch.log), matched whole against the stamp.
# A key names its shape wherever it is stored, so it never changes. A shape
# with no real capture is not added (rule 7): its stamp stays a header with
# no time until one is captured. Group ``a`` is the first non-year date
# field as written, ``b`` the second; ``ampm`` a 12-hour designator.
_SHAPES = (
    # English, month first: "10/6/2026 2:37:04 PM"
    _shape("slash-12h", _SLASH_DATE + _TIME + r"\s*(?P<ampm>AM|PM)"),
    # Spanish, Italian, French, Portuguese, day first: "06/10/2026 14:39:17"
    _shape("slash-24h", _SLASH_DATE + _TIME),
    # German, day first: "06.10.2026 14:39:58"
    _shape("dot-24h", r"(?P<a>\d{1,2})\.(?P<b>\d{1,2})\.(?P<year>\d{4})\s+" + _TIME),
    # Japanese: "2026/10/06 14:37:42"
    _shape(
        "ymd-slash-24h",
        r"(?P<year>\d{4})/(?P<a>\d{1,2})/(?P<b>\d{1,2})\s+" + _TIME,
        year_first=True,
    ),
    # Korean: "2026-10-06 오후 2:38:24"
    _shape(
        "ymd-dash-ko",
        r"(?P<year>\d{4})-(?P<a>\d{1,2})-(?P<b>\d{1,2})\s+(?P<ampm>오전|오후)\s+" + _TIME,
        year_first=True,
    ),
)


@dataclass(frozen=True, slots=True)
class HeaderStamp:
    """A stamp in a captured shape, its fields as written.

    Always a real date-time in at least one reading: a stamp that is not
    (hour 24, ``13:00:00 PM``, month 13 both ways) is refused at parsing, so
    a resolver only ever has the day/month order to decide.
    """

    text: str           # the stamp exactly as written
    shape: str          # a _SHAPES key
    year_first: bool    # the shape fixes the order; reading() ignores its argument
    year: int
    a: int              # first non-year date field as written (year-first: the month)
    b: int              # second one (year-first: the day)
    hour: int           # 0-23, any 12-hour designator already applied
    minute: int
    second: int

    def reading(self, order: str | None) -> datetime | None:
        """The stamp as naive local time with its fields read in ``order``
        (``"mdy"``/``"dmy"``). A year-first shape reads as written whatever
        ``order`` is; any other gives None with no order (or one it does not
        know), and for a date impossible in that order."""
        if self.year_first or order == "mdy":
            month, day = self.a, self.b
        elif order == "dmy":
            month, day = self.b, self.a
        else:
            return None
        try:
            return datetime(self.year, month, day, self.hour, self.minute, self.second)
        except ValueError:
            return None


@dataclass(frozen=True, slots=True)
class Header:
    """A header line's body, split at its first ``": "``."""

    stamp: str                  # the body up to that ": ", exactly as written
    context: str | None         # what follows it, stripped; None when nothing does
    parsed: HeaderStamp | None  # None: no captured shape reads it as a date and time


# A parsed stamp -> ISO-8601 naive local time, or None. Called once per header
# in file order, so a resolver that learns from one header can apply it to the
# next. Never handed an unknown-shape stamp: those are None before any resolver.
DateResolver = Callable[[HeaderStamp], str | None]

# "Once per process" for the two warnings below: the live watcher re-reads
# every second, and a warning per header would bury everything else.
_warned_patterns: set[str] = set()     # unknown-shape stamps, digits as 9
_warned_impossible: set[str] = set()   # shape keys warned by a fixed resolver
# A summarized block, once per process too, for two re-reads of the same lines
# by two Segmenters: the startup recovery reads Player-prev.log's content and
# can meet the same block again inside Player.log; and when the line that
# closes a block opens an entry still open at the poll's end, the offset holds
# at the marker, so the next poll closes the same block again.
_warned_summaries: set[tuple[str | None, tuple[str, ...]]] = set()
_SUMMARY_MARKER = "[Message summarized because"
# ":: GameObject Count = 61": the only continuation line that is quoted.
_SUMMARY_COUNT_RE = re.compile(r"^:: (?P<name>[A-Za-z ]{1,40}?) Count = (?P<n>\d{1,9})\s*$")


def _parse_stamp(stamp: str) -> HeaderStamp | None:
    for shape in _SHAPES:
        m = shape.pattern.fullmatch(stamp)
        if m is None:
            continue
        hour = int(m["hour"])
        designator = m.groupdict().get("ampm")
        if designator is not None:
            if not 1 <= hour <= 12:          # "13:00:00 PM", "0:30:00 AM": no clock we know
                return None
            hour = hour % 12 + (12 if designator in _PM_DESIGNATORS else 0)
        parsed = HeaderStamp(
            text=stamp, shape=shape.key, year_first=shape.year_first,
            year=int(m["year"]), a=int(m["a"]), b=int(m["b"]),
            hour=hour, minute=int(m["min"]), second=int(m["sec"]),
        )
        if parsed.reading("mdy") is None and parsed.reading("dmy") is None:
            return None
        return parsed
    return None


def parse_header_timestamp(body: str) -> Header | None:
    """Parse a ``[UnityCrossThreadLogger]`` line's body as a header.

    None when the body is no header: not digit-led, or no ``H:MM:SS`` before
    its first ``": "``. Otherwise the stamp as written, the context after it
    (``"Match to XYZ: GreToClientEvent"``) and the parsed stamp, which is
    None when no captured shape reads it as a date and time: a shape no
    capture has shown, or a captured one with an impossible time or date.
    Never a date: that takes an order, which is a resolver's to choose.
    """
    if not _DIGIT_RE.match(body):
        return None
    stamp, _, rest = body.partition(": ")
    if not _HEADER_TIME_RE.search(stamp):
        return None
    return Header(stamp=stamp, context=rest.strip() or None, parsed=_parse_stamp(stamp))


def fixed_resolver(order: str | None) -> DateResolver:
    """The resolver ``locale_hint`` stands for: every stamp that is not
    year-first read in ``order`` (``"mdy"``/``"dmy"``), year-first ones as
    written. With no order, or one it does not know, only year-first stamps
    get a date. A date impossible in ``order`` is None, warned once per
    process per shape."""
    known = order if order in DATE_ORDERS else None

    def resolve(parsed: HeaderStamp) -> str | None:
        when = parsed.reading(known)
        if when is not None:
            return when.isoformat()
        if known is not None and parsed.shape not in _warned_impossible:
            _warned_impossible.add(parsed.shape)
            stamp = parsed.text
            log.warning(
                "header %r is not a date when read %s; "
                "its entries are stored with no time",
                stamp, order,
            )
        return None

    return resolve


def _warn_unknown_shape(stamp: str) -> None:
    pattern = _DIGIT_RE.sub("9", stamp)
    if pattern in _warned_patterns:
        return
    _warned_patterns.add(pattern)
    log.warning(
        "header %r is not a date and time in any shape a capture has shown; "
        "its entries are stored with no time",
        stamp,
    )


class JsonAccumulator:
    """Accumulates lines of a JSON payload using brace-depth counting.

    Respects string literals and backslash escapes. Feed lines until
    :meth:`complete`; then :attr:`text` holds the exact raw payload.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._started = False

    @property
    def complete(self) -> bool:
        return self._started and self._depth == 0

    @property
    def empty(self) -> bool:
        """True before any line has been fed. Lets the segmenter tell "this is
        the first line offered to a response's accumulator" from "this is a
        continuation" without keeping its own separate flag."""
        return not self._parts

    @property
    def text(self) -> str:
        return "\n".join(self._parts)

    def feed(self, line: str) -> None:
        self._parts.append(line)
        for ch in line:
            if self._escape:
                self._escape = False
                continue
            if ch == "\\":
                if self._in_string:
                    self._escape = True
                continue
            if ch == '"':
                self._in_string = not self._in_string
                continue
            if self._in_string:
                continue
            if ch == "{":
                self._depth += 1
                self._started = True
            elif ch == "}":
                self._depth -= 1


@dataclass
class Segmenter:
    """Incremental segmenter: feed raw lines, collect completed LogEntry items.

    Stateful so the live tailer can feed partial reads. Two kinds of state
    carry across calls to ``feed_line``, and both matter across a *poll*
    boundary too, where ``reader/ingest.py`` builds a new ``Segmenter``:

    - ``_last_ts``/``_last_context``/``_last_header`` — the most recent
      header's time, the context label a following bare ``{`` line consumes,
      and the header's stamp as written. ``carry_state()`` snapshots the three;
      ``restore_carry(ts, context, header)`` seeds a new ``Segmenter`` with a
      previous one's snapshot before its first ``feed_line`` call (``header``
      is optional, for a caller that persists only the first two).
    - the pending multi-line accumulator itself (``pending`` property), for a
      payload not yet closed. An open summarized block (``_summary``) counts
      as pending too, so it is never carried: the caller holds the offset at
      its marker and feeds it whole next time. ``flush()`` drops a pending
      payload and closes an open block, which warns — for a truncated file,
      that's correct; for an incremental read that simply stopped mid-entry,
      the caller (``ingest.py``) avoids ever needing to drop it by not
      committing an offset past the entry's first line, and re-feeding it
      whole next time instead.

    ``flush()`` returns the 1-based line number the dropped entry started at,
    or ``None`` if nothing was pending — never emits it half-parsed.

    A header's date comes from ``resolve_date`` when one is given, else from
    ``fixed_resolver(locale_hint)``; passing both is an error.
    """

    locale_hint: str | None = None
    resolve_date: DateResolver | None = field(default=None, repr=False)
    _pending: JsonAccumulator | None = field(default=None, repr=False)
    _pending_kind: EntryKind = EntryKind.EVENT
    _pending_label: str | None = None
    _pending_ts: str | None = None
    _pending_header: str | None = None
    _pending_line: int = 0
    _last_ts: str | None = None       # most recent header timestamp seen
    _last_context: str | None = None  # context from that header, consumed by next payload
    _last_header: str | None = None   # that header's stamp, as written
    _line_no: int = 0
    _summary: list[str] | None = field(default=None, repr=False)  # open summarized block
    _resolve: DateResolver = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.resolve_date is None:
            self._resolve = fixed_resolver(self.locale_hint)
        elif self.locale_hint is None:
            self._resolve = self.resolve_date
        else:
            raise ValueError("Segmenter takes locale_hint or resolve_date, not both")

    def feed_line(self, raw_line: str) -> list[LogEntry]:
        """Process one line (without trailing newline). Returns completed entries."""
        self._line_no += 1
        line = raw_line.rstrip("\r")
        out: list[LogEntry] = []

        # Continuation of a multi-line payload takes priority over everything.
        if self._pending is not None:
            if (
                self._pending_kind == EntryKind.RESPONSE
                and self._pending.empty
                and not line.lstrip().startswith("{")
            ):
                # The first line offered to a response's accumulator isn't
                # JSON at all (shape 5, e.g. DeckDeleteDeck's bare "Success").
                # Emit it verbatim as the whole response and clear pending,
                # rather than feeding it to a JSON accumulator that will never
                # see a brace balance and would swallow every following line.
                out.append(
                    LogEntry(
                        kind=EntryKind.RESPONSE,
                        payload=line,
                        label=self._pending_label,
                        logged_at=self._pending_ts,
                        line_number=self._pending_line,
                        header=self._pending_header,
                    )
                )
                self._pending = None
                return out
            self._pending.feed(line)
            if self._pending.complete:
                out.append(self._finish_pending())
            return out

        if self._summary is not None:
            if line.startswith("::"):
                self._summary.append(line)
                return out
            self._close_summary()
        if line.startswith(_SUMMARY_MARKER):
            self._summary = [line]
            return out

        if line.startswith(_NOISE_PREFIXES):
            return out

        if line.startswith(UNITY_PREFIX):
            body = line[len(UNITY_PREFIX):]
            req = _REQUEST_RE.match(body)
            if req:
                entry = self._extract_inline(
                    req.group("json"), EntryKind.REQUEST, req.group("method")
                )
                if entry is not None:
                    out.append(entry)
                return out
            header = parse_header_timestamp(body)
            if header is not None:
                self._take_header(header)
                return out
            # Shape 6, "Draft.Notify {...}" and friends: the label is on the
            # same line as the payload, with no header context and no arrow.
            labeled = _LABELED_EVENT_RE.match(body)
            if labeled:
                entry = self._extract_inline(
                    labeled.group("json"), EntryKind.EVENT, labeled.group("label")
                )
                if entry is not None:
                    out.append(entry)
                return out
            return out  # other prefixed lines (STATE CHANGED etc.) are ignored for now

        resp = _RESPONSE_RE.match(line)
        if resp:
            # Payload starts on the next line.
            self._begin_pending(EntryKind.RESPONSE, resp.group("method"))
            return out

        stripped = line.lstrip()
        if stripped.startswith("{"):
            entry = self._extract_inline(line, EntryKind.EVENT, self._last_context)
            self._last_context = None
            if entry is not None:
                out.append(entry)
            return out

        return out

    def flush(self) -> int | None:
        """Drop any incomplete pending payload (e.g. file truncated mid-write).
        An open summarized block is closed too, which warns about it.

        Returns the 1-based line number the dropped entry started at, or
        ``None`` if nothing was pending.
        """
        self._close_summary()
        if self._pending is None:
            return None
        start = self._pending_line
        self._pending = None
        return start

    @property
    def pending(self) -> bool:
        """True while a multi-line payload is mid-accumulation, or a
        summarized block is open. The second keeps ``ingest.py`` from
        committing an offset past the marker, so the next poll re-reads the
        block whole and the line that ends it warns."""
        return self._pending is not None or self._summary is not None

    def carry_state(self) -> tuple[str | None, str | None, str | None]:
        """Snapshot ``(_last_ts, _last_context, _last_header)`` for a later
        ``restore_carry`` on a fresh ``Segmenter`` — see the class docstring."""
        return self._last_ts, self._last_context, self._last_header

    def restore_carry(
        self, ts: str | None, context: str | None, header: str | None = None
    ) -> None:
        """Seed carry state from a previous ``Segmenter``'s ``carry_state()``.
        Call before the first ``feed_line``."""
        self._last_ts = ts
        self._last_context = context
        self._last_header = header

    def _close_summary(self) -> None:
        """Warn once about the summarized block just ended; store nothing.

        Arena drops game-state messages over its size limit from the log and
        writes this marker with the counts instead, so the game's data has a
        gap (rule 4: warned, not guessed). A block is closed by the first line
        that does not start with ``::``, or by ``flush()``. While it is open,
        ``pending`` is True, so a poll that ends inside it commits nothing past
        the marker and the next poll re-reads the block.
        """
        block, self._summary = self._summary, None
        if block is None:
            return
        key = (self._last_header, tuple(block))
        if key in _warned_summaries:
            return
        _warned_summaries.add(key)
        counts: list[str] = []
        other = 0
        for ln in block[1:]:
            m = _SUMMARY_COUNT_RE.match(ln)
            if m:
                counts.append(f"{m['name']} Count = {m['n']}")
            elif not ln.startswith(":::"):
                other += 1
        detail = "; ".join(counts) or "no counts given"
        if other:
            detail += f" (+{other} other line(s))"
        log.warning(
            "arena summarized a message (after header %s): %s; "
            "its content is not in the log, so the game is missing it",
            self._last_header or "none", detail,
        )

    def _take_header(self, header: Header) -> None:
        # Every header replaces all three, an unreadable one included: keeping
        # the previous header's time would store its date on these entries —
        # a wrong value where rule 4 wants None.
        if header.parsed is None:
            _warn_unknown_shape(header.stamp)
            self._last_ts = None
        else:
            self._last_ts = self._resolve(header.parsed)
        self._last_header = header.stamp
        # keep only the trailing segment: "Match to X: GreToClientEvent"
        # -> "GreToClientEvent" (the useful classifier)
        self._last_context = header.context.rsplit(": ", 1)[-1] if header.context else None

    def _begin_pending(self, kind: EntryKind, label: str | None) -> None:
        self._pending = JsonAccumulator()
        self._pending_kind = kind
        self._pending_label = label
        self._pending_ts = self._last_ts
        self._pending_header = self._last_header
        self._pending_line = self._line_no + 1

    def _extract_inline(self, text: str, kind: EntryKind, label: str | None) -> LogEntry | None:
        acc = JsonAccumulator()
        acc.feed(text)
        if acc.complete:
            return LogEntry(
                kind=kind, payload=acc.text, label=label,
                logged_at=self._last_ts, line_number=self._line_no,
                header=self._last_header,
            )
        # Payload continues on following lines.
        self._pending = acc
        self._pending_kind = kind
        self._pending_label = label
        self._pending_ts = self._last_ts
        self._pending_header = self._last_header
        self._pending_line = self._line_no
        return None

    def _finish_pending(self) -> LogEntry:
        assert self._pending is not None
        entry = LogEntry(
            kind=self._pending_kind,
            payload=self._pending.text,
            label=self._pending_label,
            logged_at=self._pending_ts,
            line_number=self._pending_line,
            header=self._pending_header,
        )
        self._pending = None
        return entry


def segment_lines(lines, locale_hint: str | None = None) -> list[LogEntry]:
    """Convenience wrapper for whole-file segmentation (fixtures, tests, replay).

    Unlike ``ingest.py``'s incremental reader, this always consumes ``lines``
    to its end and has no next call to resume a still-open entry on, so a
    pending payload at the end is a genuine drop, not a held-back one — logged
    as a warning naming where it started.
    """
    seg = Segmenter(locale_hint=locale_hint)
    entries: list[LogEntry] = []
    for line in lines:
        entries.extend(seg.feed_line(line))
    dropped_at = seg.flush()
    if dropped_at is not None:
        log.warning("segment_lines: dropped an incomplete pending entry starting at line %d",
                    dropped_at)
    return entries
