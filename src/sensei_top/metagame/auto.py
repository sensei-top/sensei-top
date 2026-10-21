"""The corpus-refresh loop's one tick: which formats every refresh follows,
which sources are due, and the reclassification a store leaves owing. The
thread that calls it every few minutes lives in ``cli.py``; this module holds
no thread and no clock of its own. See docs/metagame.md, "Fetching the
corpus".

Traps this module exists to avoid:

1. **The loop never forces and never shortens a hold.** Every call passes
   ``by_hand=False`` and no ``force``: a paused source stays paused until
   ``sensei-top meta`` is run by hand, and a stored not-before is the
   fetcher's to honour, never the loop's to second-guess.
2. **Every attempted run that did not complete waits an hour**: a 429, a
   refusal or mtgo.com's 503, events stored before it included; no
   connection, a timeout, another 5xx; fbettega's GitHub unreachable; a
   refresh that raised. A run completed when it was stamped. ``fresh``,
   ``held`` and ``not_configured`` were no attempt and set no wait. The hour
   is the loop's own courtesy and appears in none of ``fetch_lines``'s
   lines: those and the Field page show only the stored not-before (for
   TopDeck, TopDeck's own time).
3. **A later stored not-before wins without the loop reading it.** The wait
   only stops the loop from calling a source; once it is over, the call goes
   through the gate, which holds the source for as long as its stored
   not-before is ahead (a 429 that asked for longer than the hour, say, or
   one a hand run of ``meta`` stored meanwhile).
4. **Nothing changes because mtgo.com refused**: the cache keeps its own
   cadence and its scope, MTGO paths included, while mtgo.com is paused. No
   source's outcome triggers or widens another's run.
5. **fbettega's freshness is its own.** ``refresh_metagame`` reads
   fbettega's own stamp, never the unscoped ``cache_age_seconds`` (see its
   docstring).
6. **One source's exception is not another's.** A refresh that raises is
   logged and waits its hour; the sources after it still run this tick.
7. **A store leaves a reclassification owing until one succeeds.** Stored
   events carry no archetype and are not yet judged against their twins
   until ``reclassify_corpus`` runs; if it fails, the next tick tries again
   even if nothing new was stored.

Clocks: ``now`` drives mtgo.com's and TopDeck's runs and the loop's waits.
fbettega's freshness is judged on the wall clock: ``refresh_metagame`` takes
no ``now``.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sensei_top.formats import FORMATS
from sensei_top.metagame import mtgo_site, source, topdeck
from sensei_top.metagame.classify_meta import classify_meta_decks
from sensei_top.metagame.dedup import mark_duplicate_events
from sensei_top.metagame.holds import MTGO, TOPDECK
from sensei_top.metagame.source import FETCH_FORMATS, RefreshResult

log = logging.getLogger(__name__)

# fbettega's name in meta_fetch_source; mtgo.com's and TopDeck's are
# holds.MTGO and holds.TOPDECK.
FBETTEGA = "fbettega"

# After an attempted run that did not complete, the loop leaves that source
# alone this long (trap 2).
BACKOFF = timedelta(hours=1)

# reclassify_corpus's two steps, one caller at a time in this process: see
# its docstring.
_RECLASSIFY_LOCK = threading.Lock()


@dataclass
class RefreshState:
    """What the loop remembers between ticks, in memory only. The caller
    keeps one for as long as it loops; a new one remembers nothing, as after
    a restart.

    ``backoff_until`` holds, per source, the time before which the loop does
    not call it again. ``reclassify_pending`` is set by a store and cleared by
    a ``reclassify_corpus`` that succeeded.
    """

    backoff_until: dict[str, datetime] = field(default_factory=dict)
    reclassify_pending: bool = False


def followed_formats(conn: sqlite3.Connection, extra: Sequence[str] = ()) -> tuple[str, ...]:
    """The formats a refresh fetches: ``FETCH_FORMATS``, every format the
    stored corpus holds that is one of ``FORMATS``, and ``extra``, in
    ``FORMATS`` order. Names match ``FORMATS`` in any case.

    A stored format outside ``FORMATS`` is not followed. A name in ``extra``
    outside it raises ``ValueError``: ``meta --format`` refuses one before it
    gets here, so it is a caller's mistake, not a format to fetch.
    """
    canonical = {f.lower(): f for f in FORMATS}
    wanted = {canonical[f.lower()] for f in FETCH_FORMATS}
    for (stored,) in conn.execute(
        "SELECT DISTINCT format FROM meta_event WHERE format IS NOT NULL"
    ):
        name = canonical.get(str(stored).strip().lower())
        if name is not None:
            wanted.add(name)
    for given in extra:
        name = canonical.get(given.strip().lower())
        if name is None:
            raise ValueError(f"{given!r} is not one of {', '.join(FORMATS)}")
        wanted.add(name)
    return tuple(f for f in FORMATS if f in wanted)


def reclassify_corpus(conn: sqlite3.Connection) -> tuple[int, dict[str, int]]:
    """``mark_duplicate_events`` and then ``classify_meta_decks``, under a
    module lock. Returns how many twins this call newly marked, and the
    classifier's counts.

    The classifier reads every deck and then replaces every classification
    in one transaction. Two threads of this process call this on their own
    connections (the corpus refresh after a store, the archetype refresh
    after new definitions); without the lock, one that read the decks before
    a store could write its rebuild after the other's, and its stale rows
    would be the ones left standing.
    """
    with _RECLASSIFY_LOCK:
        duplicates = mark_duplicate_events(conn)
        counts = classify_meta_decks(conn)
    return duplicates, counts


def _attempted_not_completed(result: RefreshResult) -> bool:
    """A run that was attempted and not stamped (trap 2). Each refresh
    answers ``updated`` only for a run it stamped, and ``failed`` for one
    that ended unstamped: fbettega's error, or the answer that ended
    mtgo.com's or TopDeck's run, events stored before it included. ``fresh``,
    ``held`` and ``not_configured`` made no attempt."""
    return result.status == "failed"


def refresh_corpus(
    conn: sqlite3.Connection, state: RefreshState, *, now: Callable[[], datetime]
) -> dict[str, RefreshResult]:
    """One tick of the loop: fbettega, mtgo.com and TopDeck, each when its
    own rules say it is due (module docstring), then ``reclassify_corpus``
    when anything was stored, this tick or one whose reclassification failed.

    ``state`` is the caller's ``RefreshState``, carried from tick to tick;
    ``now`` is the clock, returning an aware UTC time.

    Returns each called source's result keyed by its name (``fbettega``,
    ``mtgo``, ``topdeck``), in run order, ``fresh``, ``held`` and
    ``not_configured`` included. A source still inside its hour's wait, or
    whose refresh raised, has no entry. A refresh that raises, and a
    reclassification that raises, are logged at warning level and never
    raised from here.
    """
    formats = followed_formats(conn)
    runs: tuple[tuple[str, Callable[[], RefreshResult]], ...] = (
        (FBETTEGA, lambda: source.refresh_metagame(conn, formats=formats)),
        (MTGO, lambda: mtgo_site.refresh_mtgo_site(
            conn, formats=formats, now=now, by_hand=False
        )),
        (TOPDECK, lambda: topdeck.refresh_topdeck(
            conn, formats=formats, now=now, by_hand=False
        )),
    )

    results: dict[str, RefreshResult] = {}
    for name, run in runs:
        until = state.backoff_until.get(name)
        if until is not None and now() < until:
            log.debug("corpus refresh: %s waits until %s", name, until.isoformat())
            continue
        try:
            result = run()
        except Exception as exc:  # trap 6: logged, and the next source still runs
            state.backoff_until[name] = now() + BACKOFF
            log.warning(
                "corpus refresh: %s raised %s: %s; trying it again after %s",
                name, type(exc).__name__, exc, state.backoff_until[name].isoformat(),
            )
            continue
        results[name] = result
        if _attempted_not_completed(result):
            state.backoff_until[name] = now() + BACKOFF
            log.info(
                "corpus refresh: %s did not complete; trying it again after %s",
                name, state.backoff_until[name].isoformat(),
            )
        else:
            state.backoff_until.pop(name, None)
        if result.events:
            state.reclassify_pending = True

    if state.reclassify_pending:
        try:
            duplicates, counts = reclassify_corpus(conn)
        except Exception as exc:  # trap 7: still owed, so the next tick tries again
            log.warning(
                "corpus reclassification failed, to be retried next tick: %s: %s",
                type(exc).__name__, exc,
            )
        else:
            state.reclassify_pending = False
            log.info(
                "corpus reclassified: %d duplicate events set aside, "
                "%d decks classified, %d unidentified",
                duplicates, counts["classified"], counts["unclassified"],
            )
    return results
