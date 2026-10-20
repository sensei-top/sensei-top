"""The lines a corpus fetch prints, on ``sensei-top meta`` and on ``serve``'s
console: ``render`` turns a ``RefreshResult`` into them. Pure — no database,
no clock; the caller passes ``now``, and prints.

Every line is final, reviewed wording from the line catalog (kept outside
the repo). The templates below were copied from it by script, each entry's
example values replaced by fields, and are never retyped: a change of
wording goes through the catalog first. ``tests/test_metagame_lines.py``
holds every entry verbatim, in ``LINES`` (mtgo.com's) and ``TOPDECK_LINES``
(TopDeck's), keyed by section and a short name, and the tests render each:
§1.1 is mtgo.com's lines with no pause standing, §1.2 its hand-run lines
during a wait or a pause, §1.3 TopDeck's, §1.4 mtgo.com's endings on
``serve``. One line is not the
catalog's: TopDeck's "corpus is 5h old; nothing to do", which the catalog
does not list, is the fresh line ``cli.py`` printed for TopDeck before this
module, copied the same way.

mtgo.com's lines (§1.1, §1.2, §1.4) and TopDeck's (§1.3) take the same
``render`` and the same ``serve`` rule, each through its entry in
``_SOURCES``; fbettega's ``cache: …`` lines are not this module's and stay in
``cli.py::_run_metagame_refresh``. ``render`` refuses a source with no entry.

Traps this module exists to avoid:

1. **The answer decides the line, not the status.** A run that stored
   events before a server answered it is still a run that was answered; its
   line is the answer's, in its after-N form ("after 2 tournament events
   stored; keeping those" in place of the place phrase and "keeping what is
   stored (…)"). Only a run with no answer prints the plain success.
2. **The hold decides which line, not a re-derivation of the rules.** A
   first 429 and a second one, a 503's wait and a day of them, differ only
   in the hold the run left (``hold_after``); ``holds.apply_outcome`` owns
   those rules and this module reads its result. A pause standing before the
   run (``hold_before``) makes every answer a hand-run line (§1.2), "still
   paused since" the date the pause began, with "again" when the answer
   repeats the pause's cause.
3. **A not-before is never printed earlier than it is.** mtgo.com's are
   stored on the minute; one that is not is rounded up, never down.
   TopDeck's are its own time to the second, printed ``HH:MM:SS`` and
   rounded up to the second the same way. The time an answer arrived is a
   past moment and prints as a clock reads it.
4. **Dates follow the printing, not the storing.** A time carries its UTC
   date when that date is not ``now``'s, and a line with two times dates both
   when either needs it.
5. **``serve`` speaks only when the hold moved.** Into a wait, into a pause,
   a change of status or cause, or the end of a wait; never for a repeated
   503 (its not-before moves, its hold does not), an ordinary success, a
   generic failure, or a run it did not attempt. There, an mtgo.com line
   ending "try again after" ends "the next fetch is after", because the
   server retries on its own. TopDeck's lines have no such ending and print
   the same on both surfaces.
6. **The 503 lines take their own after-N form** ("HTTP 503 after 2
   tournament events stored"), not the reason's. In a hand run during a
   pause the after-N phrase composes like every other hand-run line, ahead of
   "still paused since". A day of 503s never follows a page read (a page
   read restarts ``holds.apply_outcome``'s count), so its line has no
   after-N form.
7. **A run with no pause standing, TopDeck's §1.3 first-run lines, says
   where it stopped by format, never by count.** "at Standard; nothing
   fetched" when no format had answered, "after Standard; Modern was not
   fetched" once one had. A hand run during a pause names no format and
   takes the after-N count instead, like §1.2's. Not fetched is every
   format the run did not get: the ones that went unanswered before the
   answer, the one that drew it, and the ones it left unasked, so the
   ``--format`` hint retries them all, after the not-before. The "no answer
   for" line, with its hint to retry now, follows only a success. A 401
   with nothing fetched names no format: the key was refused, not a format.
8. **", 42 s" is TopDeck's own wait.** A first 429 names the seconds only
   when TopDeck did, in ``retryAfterSeconds`` or ``Retry-After``; the hour
   the app waits when it named none is not the site's, and the line says
   "(HTTP 429)" alone.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from sensei_top.metagame.holds import MTGO, TOPDECK, Hold, HoldStatus, ceil_min
from sensei_top.metagame.source import Answer, AnswerKind, RefreshResult

META = "meta"
SERVE = "serve"
SURFACES = (META, SERVE)

# RefreshResult.status values this module reads.
_UPDATED = "updated"
_FRESH = "fresh"
_HELD = "held"
_NOT_CONFIGURED = "not_configured"

_CLOCK = "%H:%M UTC"
_DATED = "%Y-%m-%d %H:%M UTC"
_DATE = "%Y-%m-%d"
# TopDeck's not-befores are to the second (trap 3).
_TD_CLOCK = "%H:%M:%S UTC"
_TD_DATED = "%Y-%m-%d %H:%M:%S UTC"

# A 401 from TopDeck is its key.
_KEY_STATUS = 401
# The "no answer for" line's list separator, which ``_td_and`` uses too.
_TD_LIST = ", "

# The stored copy's age, in the form ``cli.py``'s cache lines print too.
_AGE = "{hours:.0f}h old"
_NO_COPY = "no cached copy"
_FRESH_HOURS = "{hours:.1f}"

# The catalog's templates. Each comment names the entry a template was
# copied from; a template cut from the middle of a line is that line's
# words between its fields.

# §1.1 success
_STORED = "mtgo: {events} tournament events stored{skipped}."

# §1.1 success
_SKIPPED = ", {count} skipped"

# §1.1 the attempt after a wait succeeds (the server's, or a hand run's)
_WAIT_OVER = "mtgo: {events} tournament events stored{skipped}; the wait is over."

# §1.2 paused, the attempt succeeds
_PAUSE_LIFTED = "mtgo: {events} tournament events stored{skipped}; the pause since {since} is lifted."  # noqa: E501

# §1.1 fresh
_NOTHING_TO_DO = "mtgo: corpus is {hours}h old; nothing to do."

# §1.1 generic failure (timeout, connection, other 5xx, index 404 or 410), nothing stored
_COULD_NOT = "mtgo: could not refresh ({reason}); keeping what is stored ({age})."

# §1.1 generic failure after events were stored
_COULD_NOT_AFTER = "mtgo: could not refresh ({reason}) after {events} tournament events stored; keeping those."  # noqa: E501

# §1.1 refused 403 at the index
_WHERE_KEPT = "{place}; keeping what is stored ({age})"

# §1.1 refused 403 after events were stored
_WHERE_AFTER = "after {events} tournament events stored; keeping those"

# §1.1 refused 403 at the index
_AT_INDEX = "at the index"

# §1.1 refused 403 at a month page
_AT_MONTH = "at the {month} archive page"

# §1.1 refused 403 at an event page
_AT_EVENT = "at an event page ({slug})"

_REFUSED = {
    # §1.1 refused 403 at the index
    403: "mtgo: refused (HTTP 403) {where}; paused until you run 'sensei-top meta' again — re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 login 401 at the index
    401: "mtgo: asked for a login (HTTP 401) {where}; paused until you run 'sensei-top meta' again — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 legal 451 at the index
    451: "mtgo: refused for legal reasons (HTTP 451) {where}; paused until you run 'sensei-top meta' again — open mtgo.com in your browser and read the notice there first.",  # noqa: E501
}

# §1.1 first 429 at the index
_RATE = "mtgo: asked for a pause (HTTP 429) {where}{ending}"

# §1.1 first 429 at the index
_TRY_AGAIN = "; try again after {time}."

# §1.4 first 429 at the index
_NEXT_FETCH = "; the next fetch is after {time}."

# §1.1 second 429 in a row, this time at the index
_RATE_TWICE = "mtgo: asked for a pause twice in a row (HTTP 429), this time {where}; paused until you run 'sensei-top meta' again — not before {time}."  # noqa: E501

# §1.1 503, nothing stored (any place; `(no cached copy)` when none)
_UNAVAILABLE = "mtgo: could not refresh ({reason}); keeping what is stored ({age}){ending}"

# §1.1 503 after events were stored
_UNAVAILABLE_AFTER = "mtgo: HTTP 503 after {events} tournament events stored; keeping those{ending}"

# §1.1 503 for a whole day (pause), no Retry-After ahead
_DAY = "mtgo: HTTP 503 for a whole day; keeping what is stored ({age}); paused until you run 'sensei-top meta' again — check that mtgo.com opens in your browser first."  # noqa: E501

# §1.1 503 for a whole day, the latest 503 carrying a Retry-After still ahead
_DAY_NOT_BEFORE = "mtgo: HTTP 503 for a whole day; keeping what is stored ({age}); paused until you run 'sensei-top meta' again, not before {time} — check that mtgo.com opens in your browser first."  # noqa: E501

# §1.2 waiting (503), before the not-before: no attempt
_WAITING = "mtgo: waiting until {until} after HTTP {status} at {at}; nothing fetched; keeping what is stored ({age})."  # noqa: E501

# §1.2 paused, with a not-before still ahead: no attempt ("HTTP 503" in place of "HTTP 429" when a
# 503 set the time)
_PAUSED_AHEAD = "mtgo: still paused since {since}; nothing fetched after HTTP {status} at {at}; keeping what is stored ({age}); run 'sensei-top meta' again after {until}."  # noqa: E501

# §1.2 paused, generic failure
_STILL_PAUSED = "; still paused since {since}; keeping what is stored ({age})"

# §1.2 paused, generic failure after events were stored
_STILL_PAUSED_AFTER = " after {events} tournament events stored; keeping those; still paused since {since}"  # noqa: E501

# §1.2 paused on 403, refused again
_AGAIN = " again"

# §1.2 paused, generic failure
_PAUSED_GENERIC = "mtgo: could not refresh ({reason}){where}."

_PAUSED_REFUSED = {
    # §1.2 paused, answered 403 while the cause is another (no "again", since kept)
    403: "mtgo: refused{again} (HTTP 403){where} — re-read Daybreak's Terms of Service before the next run.",  # noqa: E501
    # §1.2 paused, answered 401 while the cause is another
    401: "mtgo: asked for a login{again} (HTTP 401){where} — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service before the next run.",  # noqa: E501
    # §1.2 paused, answered 451 while the cause is another
    451: "mtgo: refused for legal reasons{again} (HTTP 451){where} — open mtgo.com in your browser and read the notice there before the next run.",  # noqa: E501
}

# §1.2 paused on a refusal or a 503, answered 429
_PAUSED_RATE = "mtgo: asked for a pause{again} (HTTP 429){where} — not before {time}."

# §1.2 paused on a refusal or a 429, answered 503
_PAUSED_UNAVAILABLE = "mtgo: HTTP 503{again}{where}{not_before}."

# §1.2 paused on a refusal or a 429, answered 503 with a Retry-After still ahead
_NOT_BEFORE = " — not before {time}"

# §1.3, TopDeck's templates, copied the same way. Its hand-run lines share
# §1.2's ``_STILL_PAUSED`` and ``_AGAIN``, and its success ``_SKIPPED``,
# word for word.

# §1.3 success
# (``{skipped}`` is ``_SKIPPED``, the suffix ``cli.py::_run_metagame_refresh`` prints too)
_TD_STORED = "topdeck: {events} tournament events stored{skipped}."

# §1.3 the server's own attempt ends a wait
# (``{skipped}`` as in the success line)
_TD_WAIT_OVER = "topdeck: {events} tournament events stored{skipped}; the wait is over."

# §1.3 hand run, paused, the attempt succeeds
# (``{skipped}`` as in the success line)
_TD_PAUSE_LIFTED = "topdeck: {events} tournament events stored{skipped}; the pause since {since} is lifted."  # noqa: E501

# §1.3 some formats unanswered (timeouts, 5xx)
_TD_NO_ANSWER = "topdeck: no answer for {formats}; run '{command}' to retry them."

# §1.3 some formats unanswered (timeouts, 5xx)
_TD_COMMAND = "sensei-top meta"

# §1.3 some formats unanswered (timeouts, 5xx)
_TD_FORMAT_FLAG = " --format {format}"

# §1.3 every format unanswered
_TD_COULD_NOT = "topdeck: could not refresh ({reason}); keeping what is stored ({age})."

# §1.3 no key (only with `--source topdeck`)
_TD_NO_KEY = "topdeck: no API key configured — run 'sensei-top config --set-topdeck-key KEY'."

# TopDeck's fresh line, which the catalog does not list (the module docstring)
_TD_NOTHING_TO_DO = "topdeck: corpus is {hours}h old; nothing to do."

# TopDeck's fresh line, which the catalog does not list (the module docstring)
_TD_FRESH_HOURS = "{hours:.0f}"

# §1.3 403 at the first format
_TD_AT = " at {format}; nothing fetched"

# §1.3 403 after a format was fetched
_TD_AFTER = " after {answered}; {not_fetched}"

# §1.3 403 after a format was fetched
_TD_NOT_FETCHED = "{formats} was not fetched"

# ``_TD_NOT_FETCHED`` for several formats
_TD_NOT_FETCHED_SEVERAL = "{formats} were not fetched"

# The last join of several formats: "Standard and Pioneer"
_TD_AND = " and "

_TD_REFUSED = {
    # §1.3 401, the key
    401: "topdeck: the key was not accepted (HTTP 401){where}; paused until you run 'sensei-top meta' again — set a working key with 'sensei-top config --set-topdeck-key KEY' first.",  # noqa: E501
    # §1.3 403 at the first format
    403: "topdeck: refused (HTTP 403){where}; paused until you run 'sensei-top meta' again — re-read TopDeck.gg's API terms first.",  # noqa: E501
    # §1.3 451 at the first format
    451: "topdeck: refused for legal reasons (HTTP 451){where}; paused until you run 'sensei-top meta' again — open topdeck.gg in your browser and read the notice there first.",  # noqa: E501
}

# §1.3 first 429 at the first format
_TD_RATE = "topdeck: asked for a pause (HTTP 429{wait}){where}; run '{command}' after {time}."

# §1.3 first 429 at the first format
_TD_WAIT = ", {seconds} s"

# §1.3 second 429 in a row, this time after a format was fetched
_TD_RATE_TWICE = "topdeck: asked for a pause twice in a row (HTTP 429), this time{where}; paused until you run 'sensei-top meta' again — not before {time}."  # noqa: E501

# §1.3 second 429 in a row, this time at the first format
_TD_KEPT = "; keeping what is stored ({age})"

# §1.3 hand run, waiting: no attempt
_TD_WAITING = "topdeck: waiting until {until} after HTTP {status}; nothing fetched; keeping what is stored ({age})."  # noqa: E501

# §1.3 hand run, paused with a not-before still ahead: no attempt
_TD_PAUSED_AHEAD = "topdeck: still paused since {since}; nothing fetched after HTTP {status}; keeping what is stored ({age}); run 'sensei-top meta' again after {until}."  # noqa: E501

_TD_PAUSED_REFUSED = {
    # §1.3 paused, answered 401 while the cause is another
    401: "topdeck: the key was not accepted{again} (HTTP 401){where} — set a working key with 'sensei-top config --set-topdeck-key KEY' before the next run.",  # noqa: E501
    # §1.3 paused, answered 403 while the cause is another
    403: "topdeck: refused{again} (HTTP 403){where} — re-read TopDeck.gg's API terms before the next run.",  # noqa: E501
    # §1.3 paused, answered 451 while the cause is another
    451: "topdeck: refused for legal reasons{again} (HTTP 451){where} — open topdeck.gg in your browser and read the notice there before the next run.",  # noqa: E501
}

# §1.3 paused, answered 429 while the cause is another
_TD_PAUSED_RATE = "topdeck: asked for a pause{again} (HTTP 429){where} — not before {time}."

# §1.3 paused, every format unanswered
_TD_PAUSED_GENERIC = "topdeck: could not refresh ({reason}){where}."


def render(source: str, result: RefreshResult, *, surface: str, now: datetime) -> list[str]:
    """The lines ``result`` prints on ``surface`` (``meta`` or ``serve``),
    judged at ``now``, an aware UTC time.

    On ``meta`` there is always a line. On ``serve`` there is one only after
    the server's own attempt moved the hold (trap 5), and ``[]`` otherwise,
    which the caller logs (``cli.py::_log_corpus_result``).
    """
    if surface not in SURFACES:
        raise ValueError(f"no surface {surface!r}")
    lines_for = _SOURCES.get(source)
    if lines_for is None:
        raise ValueError(f"no fetch lines for source {source!r}")
    if surface == SERVE and not _hold_moved(result):
        return []
    return lines_for(result, surface, now)


def _hold_moved(result: RefreshResult) -> bool:
    if result.status in (_FRESH, _HELD):
        return False  # no attempt, so nothing the server did
    before, after = result.hold_before, result.hold_after
    if before is None or after is None:
        return before is not after  # into a hold, or the end of one
    return before.status != after.status or before.http_status != after.http_status


def _age(seconds: float | None) -> str:
    return _AGE.format(hours=seconds / 3600) if seconds is not None else _NO_COPY


def _date(t: datetime) -> str:
    return t.astimezone(UTC).strftime(_DATE)


def _times(
    now: datetime, *times: datetime, clock: str = _CLOCK, dated: str = _DATED
) -> list[str]:
    today = now.astimezone(UTC).date()
    with_date = any(t.astimezone(UTC).date() != today for t in times)
    return [t.astimezone(UTC).strftime(dated if with_date else clock) for t in times]


def _ceil_sec(t: datetime) -> datetime:
    """``t`` rounded up to the second; a time already on the second is kept."""
    floor = t.replace(microsecond=0)
    return floor if floor == t else floor + timedelta(seconds=1)


def _not_before(
    hold: Hold | None, *, ceil: Callable[[datetime], datetime] = ceil_min
) -> datetime:
    if hold is None or hold.not_before is None:
        raise ValueError("this line needs the not-before its answer stored")
    return ceil(hold.not_before)


def _time(now: datetime, hold: Hold | None) -> str:
    """The hold's not-before, alone on its line."""
    (time,) = _times(now, _not_before(hold))
    return time


def _ahead(hold: Hold | None, now: datetime) -> bool:
    return hold is not None and hold.not_before is not None and hold.not_before > now


def _place(place: str | None) -> str:
    if place == "index":
        return _AT_INDEX
    kind, _, value = (place or "").partition(":")
    if kind == "month" and value:
        return _AT_MONTH.format(month=value)
    if kind == "event" and value:
        return _AT_EVENT.format(slug=value)
    raise ValueError(f"no place phrase for {place!r}")


def _refusal(templates: dict[int, str], http_status: int | None) -> str:
    if http_status not in templates:
        raise ValueError(f"no refusal line for HTTP {http_status}")
    return templates[http_status]


def _mtgo_lines(result: RefreshResult, surface: str, now: datetime) -> list[str]:
    return [_mtgo_line(result, surface, now)]


def _mtgo_line(result: RefreshResult, surface: str, now: datetime) -> str:
    before, answer = result.hold_before, result.answer
    if result.status == _FRESH:
        hours = _FRESH_HOURS.format(hours=(result.age_seconds or 0) / 3600)
        return _NOTHING_TO_DO.format(hours=hours)
    if result.status == _HELD:
        return _held(before, _age(result.age_seconds), now)
    if answer is None:
        if result.status != _UPDATED:
            raise ValueError(f"a {result.status!r} run carries the answer that ended it")
        return _stored(result, before)
    if before is not None and before.status == HoldStatus.PAUSED:
        return _paused_answer(result, answer, before, now)
    return _answer(result, answer, surface, now)


def _held(hold: Hold | None, age: str, now: datetime) -> str:
    """A hand run the gate held: a wait, or a pause with a not-before ahead."""
    if hold is None:
        raise ValueError("a held run needs the hold that held it")
    until, at = _times(now, _not_before(hold), hold.last_at)
    template = _WAITING if hold.status == HoldStatus.WAITING else _PAUSED_AHEAD
    # The status is the latest answer's: the one that set the not-before.
    return template.format(
        until=until, status=hold.last_status, at=at, age=age, since=_date(hold.since)
    )


def _stored(result: RefreshResult, before: Hold | None) -> str:
    skipped = _SKIPPED.format(count=result.skipped) if result.skipped else ""
    if before is None:
        return _STORED.format(events=result.events, skipped=skipped)
    if before.status == HoldStatus.WAITING:
        return _WAIT_OVER.format(events=result.events, skipped=skipped)
    return _PAUSE_LIFTED.format(events=result.events, skipped=skipped, since=_date(before.since))


def _answer(result: RefreshResult, answer: Answer, surface: str, now: datetime) -> str:
    """§1.1: an answer to a run with no pause standing."""
    age = _age(result.age_seconds)
    after_n = result.events > 0
    if answer.kind == AnswerKind.GENERIC:
        if after_n:
            return _COULD_NOT_AFTER.format(reason=answer.reason, events=result.events)
        return _COULD_NOT.format(reason=answer.reason, age=age)

    after = result.hold_after
    paused = after is not None and after.status == HoldStatus.PAUSED
    if answer.kind == AnswerKind.REFUSED:
        return _refusal(_REFUSED, answer.http_status).format(where=_where(result, answer, age))
    if answer.kind == AnswerKind.RATE and paused:
        return _RATE_TWICE.format(where=_where(result, answer, age), time=_time(now, after))
    if answer.kind == AnswerKind.UNAVAILABLE and paused:
        if _ahead(after, now):
            return _DAY_NOT_BEFORE.format(age=age, time=_time(now, after))
        return _DAY.format(age=age)

    # A wait: the server retries on its own, so serve says when.
    ending = (_NEXT_FETCH if surface == SERVE else _TRY_AGAIN).format(time=_time(now, after))
    if answer.kind == AnswerKind.RATE:
        return _RATE.format(where=_where(result, answer, age), ending=ending)
    if after_n:
        return _UNAVAILABLE_AFTER.format(events=result.events, ending=ending)
    return _UNAVAILABLE.format(reason=answer.reason, age=age, ending=ending)


def _where(result: RefreshResult, answer: Answer, age: str) -> str:
    """Where the answer came, and what is kept: the place and the stored
    copy, or, once the run had stored events, those."""
    if result.events > 0:
        return _WHERE_AFTER.format(events=result.events)
    return _WHERE_KEPT.format(place=_place(answer.place), age=age)


def _paused_answer(result: RefreshResult, answer: Answer, before: Hold, now: datetime) -> str:
    """§1.2: an answer to a hand run made during a pause."""
    since = _date(before.since)
    if result.events > 0:
        where = _STILL_PAUSED_AFTER.format(events=result.events, since=since)
    else:
        where = _STILL_PAUSED.format(since=since, age=_age(result.age_seconds))
    if answer.kind == AnswerKind.GENERIC:
        return _PAUSED_GENERIC.format(reason=answer.reason, where=where)
    again = _AGAIN if answer.http_status == before.http_status else ""
    after = result.hold_after
    if answer.kind == AnswerKind.REFUSED:
        return _refusal(_PAUSED_REFUSED, answer.http_status).format(again=again, where=where)
    if answer.kind == AnswerKind.RATE:
        return _PAUSED_RATE.format(again=again, where=where, time=_time(now, after))
    # A 503 during a pause stores a not-before only when its Retry-After
    # named one, and the line names it only while it is still ahead.
    not_before = _NOT_BEFORE.format(time=_time(now, after)) if _ahead(after, now) else ""
    return _PAUSED_UNAVAILABLE.format(again=again, where=where, not_before=not_before)


def _topdeck_lines(result: RefreshResult, surface: str, now: datetime) -> list[str]:
    """§1.3. TopDeck has no §1.4 endings: ``surface`` changes nothing here,
    only whether ``render`` asked at all."""
    before, answer = result.hold_before, result.answer
    if result.status == _NOT_CONFIGURED:
        # cli.py prints it only under --source topdeck, the entry's
        # condition; otherwise an unconfigured source is silent.
        return [_TD_NO_KEY]
    if result.status == _FRESH:
        hours = _TD_FRESH_HOURS.format(hours=(result.age_seconds or 0) / 3600)
        return [_TD_NOTHING_TO_DO.format(hours=hours)]
    if result.status == _HELD:
        return [_td_held(before, _age(result.age_seconds), now)]
    if answer is None:
        if result.status != _UPDATED:
            raise ValueError(f"a {result.status!r} run carries the answer that ended it")
        return [_td_stored(result, before), *_td_no_answer(result)]
    if before is not None and before.status == HoldStatus.PAUSED:
        return [_td_paused_answer(result, answer, before, now)]
    return [_td_answer(result, answer, now)]


def _td_time(now: datetime, hold: Hold | None) -> str:
    """The hold's not-before, TopDeck's way: to the second."""
    (time,) = _times(
        now, _not_before(hold, ceil=_ceil_sec), clock=_TD_CLOCK, dated=_TD_DATED
    )
    return time


def _td_held(hold: Hold | None, age: str, now: datetime) -> str:
    """A hand run the gate held: a wait, or a pause with a not-before ahead."""
    if hold is None:
        raise ValueError("a held run needs the hold that held it")
    template = _TD_WAITING if hold.status == HoldStatus.WAITING else _TD_PAUSED_AHEAD
    # The status is the latest answer's: the one that set the not-before.
    return template.format(
        until=_td_time(now, hold), status=hold.last_status, age=age, since=_date(hold.since)
    )


def _td_stored(result: RefreshResult, before: Hold | None) -> str:
    skipped = _SKIPPED.format(count=result.skipped) if result.skipped else ""
    if before is None:
        return _TD_STORED.format(events=result.events, skipped=skipped)
    if before.status == HoldStatus.WAITING:
        return _TD_WAIT_OVER.format(events=result.events, skipped=skipped)
    return _TD_PAUSE_LIFTED.format(
        events=result.events, skipped=skipped, since=_date(before.since)
    )


def _td_command(formats: Sequence[str]) -> str:
    return _TD_COMMAND + "".join(_TD_FORMAT_FLAG.format(format=f) for f in formats)


def _td_no_answer(result: RefreshResult) -> list[str]:
    """The line after a success whose run left formats unanswered (trap 7)."""
    if not result.unanswered:
        return []
    return [
        _TD_NO_ANSWER.format(
            formats=_TD_LIST.join(result.unanswered), command=_td_command(result.unanswered)
        )
    ]


def _td_and(formats: Sequence[str]) -> str:
    """"Standard and Pioneer"; three or more take commas before the last
    "and"."""
    if len(formats) < 2:
        return "".join(formats)
    return _TD_LIST.join(formats[:-1]) + _TD_AND + formats[-1]


def _td_not_fetched(result: RefreshResult, answer: Answer) -> tuple[str, ...]:
    """Every format the run did not get, in the order it went (trap 7)."""
    if not answer.place:
        raise ValueError(f"a TopDeck {answer.kind} answer names the format it came at")
    return (*result.unanswered, answer.place, *result.unfetched)


def _td_where(result: RefreshResult, answer: Answer) -> str:
    """Where the run stopped: at a format, or after the ones that answered."""
    if not result.answered:
        return _TD_AT.format(format=answer.place)
    not_fetched = _td_not_fetched(result, answer)
    phrase = _TD_NOT_FETCHED if len(not_fetched) == 1 else _TD_NOT_FETCHED_SEVERAL
    return _TD_AFTER.format(
        answered=_td_and(result.answered), not_fetched=phrase.format(formats=_td_and(not_fetched))
    )


def _td_wait(answer: Answer) -> str:
    """", 42 s" when TopDeck named its wait, the body's seconds before the
    header's; nothing when the hour is the app's own (trap 8)."""
    seconds = None
    if answer.retry_after_s is not None and math.isfinite(answer.retry_after_s):
        seconds = math.ceil(answer.retry_after_s)
    elif answer.retry_after is not None:
        seconds = math.ceil((answer.retry_after - answer.at).total_seconds())
    return _TD_WAIT.format(seconds=seconds) if seconds is not None else ""


def _td_answer(result: RefreshResult, answer: Answer, now: datetime) -> str:
    """§1.3: an answer to a run with no pause standing."""
    if answer.kind == AnswerKind.GENERIC:
        # Every format unanswered: nothing was fetched.
        return _TD_COULD_NOT.format(reason=answer.reason, age=_age(result.age_seconds))
    if answer.kind == AnswerKind.UNAVAILABLE:
        raise ValueError("TopDeck's 5xx is 'no answer for' its format, never an Answer")
    where = _td_where(result, answer)
    after = result.hold_after
    if answer.kind == AnswerKind.REFUSED:
        if answer.http_status == _KEY_STATUS and not result.answered:
            where = ""
        return _refusal(_TD_REFUSED, answer.http_status).format(where=where)
    if after is not None and after.status == HoldStatus.PAUSED:
        if not result.answered:
            where += _TD_KEPT.format(age=_age(result.age_seconds))
        return _TD_RATE_TWICE.format(where=where, time=_td_time(now, after))
    not_fetched = _td_not_fetched(result, answer) if result.answered else ()
    return _TD_RATE.format(
        wait=_td_wait(answer), where=where, command=_td_command(not_fetched),
        time=_td_time(now, after),
    )


def _td_paused_answer(result: RefreshResult, answer: Answer, before: Hold, now: datetime) -> str:
    """§1.3's hand-run lines: an answer to a hand run made during a pause.
    Like their §1.2 models they name no format, and once the run stored
    events they take the after-N form, as §1.2's do."""
    since = _date(before.since)
    if result.events > 0:
        where = _STILL_PAUSED_AFTER.format(events=result.events, since=since)
    else:
        where = _STILL_PAUSED.format(since=since, age=_age(result.age_seconds))
    if answer.kind == AnswerKind.GENERIC:
        return _TD_PAUSED_GENERIC.format(reason=answer.reason, where=where)
    again = _AGAIN if answer.http_status == before.http_status else ""
    if answer.kind == AnswerKind.REFUSED:
        return _refusal(_TD_PAUSED_REFUSED, answer.http_status).format(again=again, where=where)
    if answer.kind == AnswerKind.RATE:
        return _TD_PAUSED_RATE.format(
            again=again, where=where, time=_td_time(now, result.hold_after)
        )
    raise ValueError("TopDeck's 5xx is 'no answer for' its format, never an Answer")


_SOURCES: dict[str, Callable[[RefreshResult, str, datetime], list[str]]] = {
    MTGO: _mtgo_lines,
    TOPDECK: _topdeck_lines,
}
