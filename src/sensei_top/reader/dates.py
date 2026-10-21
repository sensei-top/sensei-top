"""The ``auto`` day/month order: each header's date settled on its own.

See docs/arena-log.md, "Timestamps": the rule, its six numbered steps (the
``# step N`` comments in ``auto_resolver``) and what ``header_date_order``
holds. ``--locale mdy``/``dmy`` stay as overrides (``fixed_resolver``).

Two contracts the doc doesn't spell out at this level:

- A ``HeaderStamp`` always has a real date in at least one order, so a stamp
  reaching step 6 reads as a date either way, which is what its warning says.
- The resolver runs inside ``ingest_file``'s transaction, so what it learns
  commits or rolls back with the read's rows and ``ingest_state``.

An entry stored with no time can get a dated twin on a later read
(docs/status.md, "Correctness: latent or unmeasured").
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from sensei_top.reader.segmenter import DATE_ORDERS, DateResolver, HeaderStamp

log = logging.getLogger(__name__)

# The --locale value that means "settle each header" rather than one order.
AUTO = "auto"

# Step 4's window around the file's last write. Before: a session up to a week
# long is dated by its own file. After: the file keeps growing between the stat
# and the read, and a clock can move; a day is slack for both.
_WINDOW_BEFORE = timedelta(days=7)
_WINDOW_AFTER = timedelta(days=1)

# "Once per process per file and shape" for both warnings: the live watcher
# re-reads every second, and a warning per header would bury everything else.
_warned_unsettled: set[tuple[str, str]] = set()      # (file name, shape)
_warned_contradicted: set[tuple[str, str]] = set()   # (file name, shape)


@dataclass(frozen=True, slots=True)
class _Learned:
    order: str        # "mdy" or "dmy"
    settled_by: str   # the stamp that taught it, as written


def _load_learned(conn: sqlite3.Connection) -> dict[str, _Learned]:
    rows = conn.execute("SELECT shape, date_order, settled_by FROM header_date_order")
    return {shape: _Learned(order, settled_by) for shape, order, settled_by in rows}


def _store_learned(
    conn: sqlite3.Connection, shape: str, learned: _Learned, source_file: str
) -> None:
    conn.execute(
        """
        INSERT INTO header_date_order (shape, date_order, settled_by, source_file, settled_at)
             VALUES (?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        ON CONFLICT (shape) DO UPDATE SET
             date_order = excluded.date_order,
             settled_by = excluded.settled_by,
             source_file = excluded.source_file,
             settled_at = excluded.settled_at
        """,
        (shape, learned.order, learned.settled_by, source_file),
    )


def auto_resolver(
    conn: sqlite3.Connection, *, source_file: str, last_write: datetime
) -> DateResolver:
    """The ``auto`` resolver for one read of one file (module docstring).

    ``source_file`` is the file's name as ``raw_events.source_file`` records
    it; ``last_write`` its mtime as naive local time. The learned orders are
    read here, once, so the caller decides where that read falls relative to
    its transaction. Writes go through ``conn`` as the resolver learns.
    """
    learned = _load_learned(conn)
    earliest, latest = last_write - _WINDOW_BEFORE, last_write + _WINDOW_AFTER
    written = last_write.strftime("%Y-%m-%d %H:%M")

    def learn(parsed: HeaderStamp, order: str) -> None:
        previous = learned.get(parsed.shape)
        if previous is not None and previous.order == order:
            return
        if previous is not None:
            _warn_contradicted(source_file, parsed, order, previous)
        learned[parsed.shape] = _Learned(order, parsed.text)
        _store_learned(conn, parsed.shape, learned[parsed.shape], source_file)

    def resolve(parsed: HeaderStamp) -> str | None:
        if parsed.year_first:                                   # step 1
            when = parsed.reading(None)
            return when.isoformat() if when is not None else None
        readings = {order: parsed.reading(order) for order in DATE_ORDERS}
        real = {order: when for order, when in readings.items() if when is not None}
        if not real:
            # Refused at parsing (HeaderStamp's docstring); never a guess here.
            return None
        if len(real) == 1:                                      # step 2
            ((order, when),) = real.items()
            learn(parsed, order)
            return when.isoformat()
        if len(set(real.values())) == 1:                        # step 3
            return next(iter(real.values())).isoformat()
        fits = [order for order, when in real.items() if earliest <= when <= latest]
        if fits:                                                # step 4
            learn(parsed, fits[0])
            return real[fits[0]].isoformat()
        known = learned.get(parsed.shape)
        if known is not None:                                   # step 5
            return real[known.order].isoformat()
        _warn_unsettled(source_file, parsed, written)           # step 6
        return None

    return resolve


def _warn_unsettled(file_name: str, parsed: HeaderStamp, last_write: str) -> None:
    key = (file_name, parsed.shape)
    if key in _warned_unsettled:
        return
    _warned_unsettled.add(key)
    stamp, shape = parsed.text, parsed.shape
    log.warning(
        "%s: header %r reads as a date either way, is not within the week "
        "before the file's last write (%s), and this database has not "
        "learned the order of %s headers; its entries are stored with no time",
        file_name, stamp, last_write, shape,
    )


def _warn_contradicted(
    file_name: str, parsed: HeaderStamp, new_order: str, previous: _Learned
) -> None:
    key = (file_name, parsed.shape)
    if key in _warned_contradicted:
        return
    _warned_contradicted.add(key)
    stamp, shape = parsed.text, parsed.shape
    old_order, old_settled_by = previous.order, previous.settled_by
    log.warning(
        "%s: header %r reads %s, but this database had learned %s for %s "
        "headers (from %r); %s from now on, and rows already stored keep "
        "their dates",
        file_name, stamp, new_order, old_order, shape, old_settled_by, new_order,
    )
