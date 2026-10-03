"""Log entry segmentation for Arena's Player.log.

Verified against a real 2026.62 log (Steam/Proton, Linux host). Five entry
shapes matter; everything else is engine noise:

1. Single-line request::

       [UnityCrossThreadLogger]==> GetFormats {"id":"...","request":"{ }"}

   Method name after the arrow, JSON to end of line. The ``request`` field is
   string-escaped JSON-in-JSON; the reader stores it raw, the projector does
   the second deserialization pass.

2. Response::

       [UnityCrossThreadLogger]8/13/2026 2:40:28 PM
       <== GetFormats(7bef1bb4-...)
       {"NodeStates":{...}}

   The ``<==`` line is bare (no prefix), carries method + request UUID, and the
   payload starts on the *next* line and may span many lines.

3. Prefixed event with header, payload on following line(s)::

       [UnityCrossThreadLogger]8/13/2026 2:49:21 PM: D67C... to Match: ClientToGremessage
       {
         "requestId": 3,
         ...multi-line...
       }

4. Bare JSON event line(s) with no preceding header at all (match service
   events such as ``matchGameRoomStateChangedEvent`` and ``greToClientEvent``
   often appear this way).

5. Response with a non-JSON body — observed for real on ``DeckDeleteDeck``::

       [UnityCrossThreadLogger]9/23/2026 5:30:38 PM
       <== DeckDeleteDeck(00000000-0000-0000-0000-000000000001)
       Success
       Can't find pet for deck Some Deck (00000000-0000-0000-0000-000000000002)

   A response's payload is expected to start with ``{`` on the line right
   after ``<==``. When it doesn't, that first line is emitted verbatim as the
   response's payload instead of being fed to the JSON accumulator — which
   would otherwise never see a ``{``/``}`` pair balance and swallow every
   following line, requests included, until one happened to balance by
   accident. This is structural, not semantic: the reader still learns
   nothing about what ``DeckDeleteDeck``/``Success`` means, and the
   projector's "unparseable payload" warning on that row is correct.

JSON payloads are extracted by brace-depth counting that respects string
literals and backslash escapes — payloads legitimately contain ``{``/``}``
inside strings (card text, escaped nested JSON), so naive counting corrupts.

Timestamps: header timestamps are in the user's system locale and therefore
ambiguous (``3/7/2026``). The segmenter takes an optional ``locale_hint``
(``"mdy"`` or ``"dmy"``); with no hint, or an unparseable header, ``logged_at``
is ``None`` — never synthesized (brief §6).
"""

from __future__ import annotations

import logging
import re
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
# "8/13/2026 2:49:21 PM" (12-hour) or "13/8/2026 14:49:21" (24-hour),
# optionally followed by ": <context>"
_HEADER_TS_RE = re.compile(
    r"^(?P<a>\d{1,2})/(?P<b>\d{1,2})/(?P<year>\d{4})\s+"
    r"(?P<hour>\d{1,2}):(?P<min>\d{2}):(?P<sec>\d{2})\s*(?P<ampm>AM|PM)?(?P<rest>:.*)?$"
)


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


def parse_header_timestamp(text: str, locale_hint: str | None) -> tuple[str | None, str | None]:
    """Parse a Unity header timestamp line. Returns (iso_timestamp, context).

    ``context`` is any trailing ": Match to XYZ: GreToClientEvent" part.
    Both clocks are accepted: 12-hour with an ``AM``/``PM`` designator, or
    24-hour with none. Returns (None, None) when the line is not a timestamp
    header, and (None, context) when a hint is missing/invalid, an hour is
    impossible for its clock (e.g. "13:00 PM"), or the date is impossible —
    we keep the context label but refuse to guess the timestamp.
    """
    m = _HEADER_TS_RE.match(text)
    if not m:
        return None, None
    context = (m.group("rest") or "").lstrip(": ").strip() or None
    if locale_hint not in ("mdy", "dmy"):
        return None, context
    a, b = int(m.group("a")), int(m.group("b"))
    month, day = (a, b) if locale_hint == "mdy" else (b, a)
    hour = int(m.group("hour"))
    ampm = m.group("ampm")
    if ampm is not None:
        if not 1 <= hour <= 12:          # "13:00 PM", "0:30 AM": not a clock we know
            return None, context
        hour = hour % 12 + (12 if ampm == "PM" else 0)
    # no designator: the hour as written (0-23); datetime() rejects 24+ → (None, context)
    try:
        ts = datetime(
            int(m.group("year")), month, day, hour, int(m.group("min")), int(m.group("sec"))
        )
    except ValueError:
        return None, context
    return ts.isoformat(), context


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
    boundary too (``reader/ingest.py``, which used to build a fresh
    ``Segmenter`` per read and lose both):

    - ``_last_ts``/``_last_context`` — the most recent header timestamp and
      the context label a following bare ``{`` line consumes. ``carry_state()``
      snapshots this pair; ``restore_carry(ts, context)`` seeds a new
      ``Segmenter`` with a previous one's snapshot before its first
      ``feed_line`` call.
    - the pending multi-line accumulator itself (``pending`` property), for a
      payload not yet closed. ``flush()`` drops it — for a truncated file,
      that's correct; for an incremental read that simply stopped mid-entry,
      the caller (``ingest.py``) avoids ever needing to drop it by not
      committing an offset past the entry's first line, and re-feeding it
      whole next time instead.

    ``flush()`` returns the 1-based line number the dropped entry started at,
    or ``None`` if nothing was pending — never emits it half-parsed.
    """

    locale_hint: str | None = None
    _pending: JsonAccumulator | None = field(default=None, repr=False)
    _pending_kind: EntryKind = EntryKind.EVENT
    _pending_label: str | None = None
    _pending_ts: str | None = None
    _pending_line: int = 0
    _last_ts: str | None = None       # most recent header timestamp seen
    _last_context: str | None = None  # context from that header, consumed by next payload
    _line_no: int = 0

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
                # JSON at all (entry shape 5 in the module docstring, e.g.
                # DeckDeleteDeck's bare "Success"). Emit it verbatim as the
                # whole response and clear pending, rather than feeding it to
                # a JSON accumulator that will never see a brace balance and
                # would otherwise swallow every following line looking for one.
                out.append(
                    LogEntry(
                        kind=EntryKind.RESPONSE,
                        payload=line,
                        label=self._pending_label,
                        logged_at=self._pending_ts,
                        line_number=self._pending_line,
                    )
                )
                self._pending = None
                return out
            self._pending.feed(line)
            if self._pending.complete:
                out.append(self._finish_pending())
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
            ts, context = parse_header_timestamp(body, self.locale_hint)
            if ts is not None or context is not None:
                self._last_ts = ts
                # keep only the trailing segment: "Match to X: GreToClientEvent"
                # -> "GreToClientEvent" (the useful classifier)
                self._last_context = context.rsplit(": ", 1)[-1] if context else None
                return out
            # "Draft.Notify {...}" and friends: the label is on the same line as
            # the payload, with no header context and no "==>" arrow. Without
            # this these lines were dropped outright.
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

        Returns the 1-based line number the dropped entry started at, or
        ``None`` if nothing was pending.
        """
        if self._pending is None:
            return None
        start = self._pending_line
        self._pending = None
        return start

    @property
    def pending(self) -> bool:
        """True while a multi-line payload is mid-accumulation."""
        return self._pending is not None

    def carry_state(self) -> tuple[str | None, str | None]:
        """Snapshot ``(_last_ts, _last_context)`` for a later ``restore_carry``
        on a fresh ``Segmenter`` — see the class docstring."""
        return self._last_ts, self._last_context

    def restore_carry(self, ts: str | None, context: str | None) -> None:
        """Seed carry state from a previous ``Segmenter``'s ``carry_state()``.
        Call before the first ``feed_line``."""
        self._last_ts = ts
        self._last_context = context

    # -- internals ----------------------------------------------------------

    def _begin_pending(self, kind: EntryKind, label: str | None) -> None:
        self._pending = JsonAccumulator()
        self._pending_kind = kind
        self._pending_label = label
        self._pending_ts = self._last_ts
        self._pending_line = self._line_no + 1

    def _extract_inline(self, text: str, kind: EntryKind, label: str | None) -> LogEntry | None:
        acc = JsonAccumulator()
        acc.feed(text)
        if acc.complete:
            return LogEntry(
                kind=kind, payload=acc.text, label=label,
                logged_at=self._last_ts, line_number=self._line_no,
            )
        # Payload continues on following lines.
        self._pending = acc
        self._pending_kind = kind
        self._pending_label = label
        self._pending_ts = self._last_ts
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
