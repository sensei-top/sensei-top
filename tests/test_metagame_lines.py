"""The fetch lines (plan 14, S3): every entry of the line catalog's §1,
mtgo.com's (``lines.md`` §1.1, §1.2 and §1.4) and TopDeck's (§1.3), rendered
from the result its condition describes, and ``serve``'s silence when the
hold did not move.

The expected lines are the catalog's, copied into ``LINES`` by script and
never retyped. Each case builds a ``RefreshResult`` by hand whose values are
the entry's examples (``lines.md`` line 3: a date, a not-before time, the
stored copy's age, the count stored, the status, the page): the holds are the
ones S3's transitions leave, worked out from the rules rather than produced
by ``apply_outcome``, so a case says what the line is for, not what the code
did. No database, no network.

A line the catalog states as a substitution of an entry (``(no cached
copy)``, "HTTP 503 in place of HTTP 429", the date rule, the hand-run after-N
rule of ``followup4.md:83-88``) is built from that entry by the substitution
the catalog names. A ``serve`` case is the server's own attempt, never a
hand run, so it passes ``by_hand=False``.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from sensei_top.metagame.fetch_lines import render
from sensei_top.metagame.holds import MTGO, TOPDECK, Hold, HoldStatus
from sensei_top.metagame.source import Answer, AnswerKind, RefreshResult, answer_kind

# lines.md §1.1, §1.2 and §1.4, every entry, copied by script and never
# retyped. The key is the section and a short name for the entry, whose
# label is the comment above it.
LINES = {
    # §1.1 success
    ("1.1", "success"): "mtgo: 4 tournament events stored, 2 skipped.",
    # §1.1 fresh
    ("1.1", "fresh"): "mtgo: corpus is 1.2h old; nothing to do.",
    # §1.1 generic failure (timeout, connection, other 5xx, index 404 or 410), nothing stored
    ("1.1", "generic"): "mtgo: could not refresh (timed out); keeping what is stored (5h old).",
    # §1.1 generic failure after events were stored
    ("1.1", "generic after"): "mtgo: could not refresh (timed out) after 2 tournament events stored; keeping those.",  # noqa: E501
    # §1.1 refused 403 at the index
    ("1.1", "403 index"): "mtgo: refused (HTTP 403) at the index; keeping what is stored (5h old); paused until you run 'sensei-top meta' again — re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 refused 403 at a month page
    ("1.1", "403 month"): "mtgo: refused (HTTP 403) at the 2026-09 archive page; keeping what is stored (5h old); paused until you run 'sensei-top meta' again — re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 refused 403 at an event page
    ("1.1", "403 event"): "mtgo: refused (HTTP 403) at an event page (standard-league-2026-10-03); keeping what is stored (5h old); paused until you run 'sensei-top meta' again — re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 refused 403 after events were stored
    ("1.1", "403 after"): "mtgo: refused (HTTP 403) after 2 tournament events stored; keeping those; paused until you run 'sensei-top meta' again — re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 login 401 at the index
    ("1.1", "401 index"): "mtgo: asked for a login (HTTP 401) at the index; keeping what is stored (5h old); paused until you run 'sensei-top meta' again — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 login 401 at a month page
    ("1.1", "401 month"): "mtgo: asked for a login (HTTP 401) at the 2026-09 archive page; keeping what is stored (5h old); paused until you run 'sensei-top meta' again — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 login 401 at an event page
    ("1.1", "401 event"): "mtgo: asked for a login (HTTP 401) at an event page (standard-league-2026-10-03); keeping what is stored (5h old); paused until you run 'sensei-top meta' again — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 login 401 after events were stored
    ("1.1", "401 after"): "mtgo: asked for a login (HTTP 401) after 2 tournament events stored; keeping those; paused until you run 'sensei-top meta' again — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service first.",  # noqa: E501
    # §1.1 legal 451 at the index
    ("1.1", "451 index"): "mtgo: refused for legal reasons (HTTP 451) at the index; keeping what is stored (5h old); paused until you run 'sensei-top meta' again — open mtgo.com in your browser and read the notice there first.",  # noqa: E501
    # §1.1 legal 451 at a month page
    ("1.1", "451 month"): "mtgo: refused for legal reasons (HTTP 451) at the 2026-09 archive page; keeping what is stored (5h old); paused until you run 'sensei-top meta' again — open mtgo.com in your browser and read the notice there first.",  # noqa: E501
    # §1.1 legal 451 at an event page
    ("1.1", "451 event"): "mtgo: refused for legal reasons (HTTP 451) at an event page (standard-league-2026-10-03); keeping what is stored (5h old); paused until you run 'sensei-top meta' again — open mtgo.com in your browser and read the notice there first.",  # noqa: E501
    # §1.1 legal 451 after events were stored
    ("1.1", "451 after"): "mtgo: refused for legal reasons (HTTP 451) after 2 tournament events stored; keeping those; paused until you run 'sensei-top meta' again — open mtgo.com in your browser and read the notice there first.",  # noqa: E501
    # §1.1 first 429 at the index
    ("1.1", "429 index"): "mtgo: asked for a pause (HTTP 429) at the index; keeping what is stored (5h old); try again after 17:10 UTC.",  # noqa: E501
    # §1.1 first 429 at a month page
    ("1.1", "429 month"): "mtgo: asked for a pause (HTTP 429) at the 2026-09 archive page; keeping what is stored (5h old); try again after 17:10 UTC.",  # noqa: E501
    # §1.1 first 429 at an event page
    ("1.1", "429 event"): "mtgo: asked for a pause (HTTP 429) at an event page (standard-league-2026-10-03); keeping what is stored (5h old); try again after 17:10 UTC.",  # noqa: E501
    # §1.1 first 429 after events were stored
    ("1.1", "429 after"): "mtgo: asked for a pause (HTTP 429) after 2 tournament events stored; keeping those; try again after 17:10 UTC.",  # noqa: E501
    # §1.1 second 429 in a row, this time at the index
    ("1.1", "429 twice index"): "mtgo: asked for a pause twice in a row (HTTP 429), this time at the index; keeping what is stored (3h old); paused until you run 'sensei-top meta' again — not before 17:10 UTC.",  # noqa: E501
    # §1.1 second 429 in a row, this time at a month page
    ("1.1", "429 twice month"): "mtgo: asked for a pause twice in a row (HTTP 429), this time at the 2026-09 archive page; keeping what is stored (3h old); paused until you run 'sensei-top meta' again — not before 17:10 UTC.",  # noqa: E501
    # §1.1 second 429 in a row, this time at an event page
    ("1.1", "429 twice event"): "mtgo: asked for a pause twice in a row (HTTP 429), this time at an event page (standard-league-2026-10-03); keeping what is stored (3h old); paused until you run 'sensei-top meta' again — not before 17:10 UTC.",  # noqa: E501
    # §1.1 second 429 in a row, this time after events were stored
    ("1.1", "429 twice after"): "mtgo: asked for a pause twice in a row (HTTP 429), this time after 2 tournament events stored; keeping those; paused until you run 'sensei-top meta' again — not before 17:10 UTC.",  # noqa: E501
    # §1.1 503, nothing stored (any place; `(no cached copy)` when none)
    ("1.1", "503"): "mtgo: could not refresh (HTTP 503 Service Unavailable); keeping what is stored (5h old); try again after 17:10 UTC.",  # noqa: E501
    # §1.1 503 after events were stored
    ("1.1", "503 after"): "mtgo: HTTP 503 after 2 tournament events stored; keeping those; try again after 17:10 UTC.",  # noqa: E501
    # §1.1 503 for a whole day (pause), no Retry-After ahead
    ("1.1", "503 day"): "mtgo: HTTP 503 for a whole day; keeping what is stored (26h old); paused until you run 'sensei-top meta' again — check that mtgo.com opens in your browser first.",  # noqa: E501
    # §1.1 503 for a whole day, the latest 503 carrying a Retry-After still ahead
    ("1.1", "503 day not before"): "mtgo: HTTP 503 for a whole day; keeping what is stored (26h old); paused until you run 'sensei-top meta' again, not before 17:10 UTC — check that mtgo.com opens in your browser first.",  # noqa: E501
    # §1.1 the attempt after a wait succeeds (the server's, or a hand run's)
    ("1.1", "wait over"): "mtgo: 4 tournament events stored, 2 skipped; the wait is over.",
    # §1.2 waiting (503), before the not-before: no attempt
    ("1.2", "waiting 503"): "mtgo: waiting until 17:10 UTC after HTTP 503 at 14:10 UTC; nothing fetched; keeping what is stored (5h old).",  # noqa: E501
    # §1.2 waiting (429), before the not-before: no attempt
    ("1.2", "waiting 429"): "mtgo: waiting until 17:10 UTC after HTTP 429 at 14:10 UTC; nothing fetched; keeping what is stored (5h old).",  # noqa: E501
    # §1.2 waiting, the answer and the not-before on different dates (the date rule, §0)
    ("1.2", "waiting dated"): "mtgo: waiting until 2026-10-06 16:00 UTC after HTTP 503 at 2026-10-05 23:40 UTC; nothing fetched; keeping what is stored (5h old).",  # noqa: E501
    # §1.2 paused, with a not-before still ahead: no attempt ("HTTP 503" in place of "HTTP
    # 429" when a 503 set the time, F4:146)
    ("1.2", "paused ahead"): "mtgo: still paused since 2026-10-05; nothing fetched after HTTP 429 at 14:10 UTC; keeping what is stored (5h old); run 'sensei-top meta' again after 17:10 UTC.",  # noqa: E501
    # §1.2 paused, the attempt succeeds
    ("1.2", "pause lifted"): "mtgo: 4 tournament events stored, 2 skipped; the pause since 2026-10-05 is lifted.",  # noqa: E501
    # §1.2 paused on 403, refused again
    ("1.2", "403 again"): "mtgo: refused again (HTTP 403); still paused since 2026-10-05; keeping what is stored (31h old) — re-read Daybreak's Terms of Service before the next run.",  # noqa: E501
    # §1.2 paused on 401, 401 again
    ("1.2", "401 again"): "mtgo: asked for a login again (HTTP 401); still paused since 2026-10-05; keeping what is stored (31h old) — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service before the next run.",  # noqa: E501
    # §1.2 paused on 451, 451 again
    ("1.2", "451 again"): "mtgo: refused for legal reasons again (HTTP 451); still paused since 2026-10-05; keeping what is stored (31h old) — open mtgo.com in your browser and read the notice there before the next run.",  # noqa: E501
    # §1.2 paused on 503, 503 again
    ("1.2", "503 again"): "mtgo: HTTP 503 again; still paused since 2026-10-05; keeping what is stored (31h old).",  # noqa: E501
    # §1.2 paused on 503, 503 again with a Retry-After still ahead
    ("1.2", "503 again not before"): "mtgo: HTTP 503 again; still paused since 2026-10-05; keeping what is stored (31h old) — not before 18:10 UTC.",  # noqa: E501
    # §1.2 paused on 429, 429 again
    ("1.2", "429 again"): "mtgo: asked for a pause again (HTTP 429); still paused since 2026-10-05; keeping what is stored (31h old) — not before 18:10 UTC.",  # noqa: E501
    # §1.2 paused, answered 403 while the cause is another (no "again", since kept)
    ("1.2", "403 other"): "mtgo: refused (HTTP 403); still paused since 2026-10-05; keeping what is stored (31h old) — re-read Daybreak's Terms of Service before the next run.",  # noqa: E501
    # §1.2 paused, answered 401 while the cause is another
    ("1.2", "401 other"): "mtgo: asked for a login (HTTP 401); still paused since 2026-10-05; keeping what is stored (31h old) — Sensei Top never logs in to mtgo.com; re-read Daybreak's Terms of Service before the next run.",  # noqa: E501
    # §1.2 paused, answered 451 while the cause is another
    ("1.2", "451 other"): "mtgo: refused for legal reasons (HTTP 451); still paused since 2026-10-05; keeping what is stored (31h old) — open mtgo.com in your browser and read the notice there before the next run.",  # noqa: E501
    # §1.2 paused on a refusal or a 429, answered 503
    ("1.2", "503 other"): "mtgo: HTTP 503; still paused since 2026-10-05; keeping what is stored (31h old).",  # noqa: E501
    # §1.2 paused on a refusal or a 429, answered 503 with a Retry-After still ahead
    ("1.2", "503 other not before"): "mtgo: HTTP 503; still paused since 2026-10-05; keeping what is stored (31h old) — not before 18:10 UTC.",  # noqa: E501
    # §1.2 paused on a refusal or a 503, answered 429
    ("1.2", "429 other"): "mtgo: asked for a pause (HTTP 429); still paused since 2026-10-05; keeping what is stored (31h old) — not before 18:10 UTC.",  # noqa: E501
    # §1.2 paused, generic failure
    ("1.2", "generic"): "mtgo: could not refresh (timed out); still paused since 2026-10-05; keeping what is stored (31h old).",  # noqa: E501
    # §1.2 paused, generic failure with an HTTP reason
    ("1.2", "generic http"): "mtgo: could not refresh (HTTP 404 Not Found); still paused since 2026-10-05; keeping what is stored (31h old).",  # noqa: E501
    # §1.2 paused, refused again after events were stored
    ("1.2", "403 again after"): "mtgo: refused again (HTTP 403) after 2 tournament events stored; keeping those; still paused since 2026-10-05 — re-read Daybreak's Terms of Service before the next run.",  # noqa: E501
    # §1.2 paused, generic failure after events were stored
    ("1.2", "generic after"): "mtgo: could not refresh (timed out) after 2 tournament events stored; keeping those; still paused since 2026-10-05.",  # noqa: E501
    # §1.4 first 429 at the index
    ("1.4", "429 index"): "mtgo: asked for a pause (HTTP 429) at the index; keeping what is stored (5h old); the next fetch is after 17:10 UTC.",  # noqa: E501
    # §1.4 first 429 at a month page
    ("1.4", "429 month"): "mtgo: asked for a pause (HTTP 429) at the 2026-09 archive page; keeping what is stored (5h old); the next fetch is after 17:10 UTC.",  # noqa: E501
    # §1.4 first 429 at an event page
    ("1.4", "429 event"): "mtgo: asked for a pause (HTTP 429) at an event page (standard-league-2026-10-03); keeping what is stored (5h old); the next fetch is after 17:10 UTC.",  # noqa: E501
    # §1.4 first 429 after events were stored
    ("1.4", "429 after"): "mtgo: asked for a pause (HTTP 429) after 2 tournament events stored; keeping those; the next fetch is after 17:10 UTC.",  # noqa: E501
    # §1.4 503, nothing stored (any place; `(no cached copy)` when none)
    ("1.4", "503"): "mtgo: could not refresh (HTTP 503 Service Unavailable); keeping what is stored (5h old); the next fetch is after 17:10 UTC.",  # noqa: E501
    # §1.4 503 after events were stored
    ("1.4", "503 after"): "mtgo: HTTP 503 after 2 tournament events stored; keeping those; the next fetch is after 17:10 UTC.",  # noqa: E501
}

# lines.md §1.3, every entry, copied by script and never retyped, keyed
# the same way.
TOPDECK_LINES = {
    # §1.3 success
    ("1.3", "success"): "topdeck: 3 tournament events stored.",
    # §1.3 some formats unanswered (timeouts, 5xx)
    ("1.3", "unanswered"): "topdeck: no answer for Modern; run 'sensei-top meta --format Modern' to retry them.",  # noqa: E501
    # §1.3 every format unanswered
    ("1.3", "all unanswered"): "topdeck: could not refresh (timed out); keeping what is stored (24h old).",  # noqa: E501
    # §1.3 no key (only with `--source topdeck`)
    ("1.3", "no key"): "topdeck: no API key configured — run 'sensei-top config --set-topdeck-key KEY'.",  # noqa: E501
    # §1.3 401, the key
    ("1.3", "401"): "topdeck: the key was not accepted (HTTP 401); paused until you run 'sensei-top meta' again — set a working key with 'sensei-top config --set-topdeck-key KEY' first.",  # noqa: E501
    # §1.3 401 after a format was fetched
    ("1.3", "401 after"): "topdeck: the key was not accepted (HTTP 401) after Standard; Modern was not fetched; paused until you run 'sensei-top meta' again — set a working key with 'sensei-top config --set-topdeck-key KEY' first.",  # noqa: E501
    # §1.3 403 after a format was fetched
    ("1.3", "403 after"): "topdeck: refused (HTTP 403) after Standard; Modern was not fetched; paused until you run 'sensei-top meta' again — re-read TopDeck.gg's API terms first.",  # noqa: E501
    # §1.3 403 at the first format
    ("1.3", "403 at"): "topdeck: refused (HTTP 403) at Standard; nothing fetched; paused until you run 'sensei-top meta' again — re-read TopDeck.gg's API terms first.",  # noqa: E501
    # §1.3 451 at the first format
    ("1.3", "451 at"): "topdeck: refused for legal reasons (HTTP 451) at Standard; nothing fetched; paused until you run 'sensei-top meta' again — open topdeck.gg in your browser and read the notice there first.",  # noqa: E501
    # §1.3 451 after a format was fetched
    ("1.3", "451 after"): "topdeck: refused for legal reasons (HTTP 451) after Standard; Modern was not fetched; paused until you run 'sensei-top meta' again — open topdeck.gg in your browser and read the notice there first.",  # noqa: E501
    # §1.3 first 429 after a format was fetched
    ("1.3", "429 after"): "topdeck: asked for a pause (HTTP 429, 42 s) after Standard; Modern was not fetched; run 'sensei-top meta --format Modern' after 14:03:10 UTC.",  # noqa: E501
    # §1.3 first 429 at the first format
    ("1.3", "429 at"): "topdeck: asked for a pause (HTTP 429, 42 s) at Standard; nothing fetched; run 'sensei-top meta' after 14:03:10 UTC.",  # noqa: E501
    # §1.3 second 429 in a row, this time at the first format
    ("1.3", "429 twice at"): "topdeck: asked for a pause twice in a row (HTTP 429), this time at Standard; nothing fetched; keeping what is stored (24h old); paused until you run 'sensei-top meta' again — not before 14:03:10 UTC.",  # noqa: E501
    # §1.3 second 429 in a row, this time after a format was fetched
    ("1.3", "429 twice after"): "topdeck: asked for a pause twice in a row (HTTP 429), this time after Standard; Modern was not fetched; paused until you run 'sensei-top meta' again — not before 14:03:10 UTC.",  # noqa: E501
    # §1.3 hand run, waiting: no attempt
    ("1.3", "waiting"): "topdeck: waiting until 14:03:10 UTC after HTTP 429; nothing fetched; keeping what is stored (24h old).",  # noqa: E501
    # §1.3 hand run, paused with a not-before still ahead: no attempt
    ("1.3", "paused ahead"): "topdeck: still paused since 2026-10-05; nothing fetched after HTTP 429; keeping what is stored (24h old); run 'sensei-top meta' again after 14:03:10 UTC.",  # noqa: E501
    # §1.3 hand run, paused, the attempt succeeds
    ("1.3", "pause lifted"): "topdeck: 3 tournament events stored; the pause since 2026-10-05 is lifted.",  # noqa: E501
    # §1.3 paused on 401, 401 again
    ("1.3", "401 again"): "topdeck: the key was not accepted again (HTTP 401); still paused since 2026-10-05; keeping what is stored (31h old) — set a working key with 'sensei-top config --set-topdeck-key KEY' before the next run.",  # noqa: E501
    # §1.3 paused on 403, 403 again
    ("1.3", "403 again"): "topdeck: refused again (HTTP 403); still paused since 2026-10-05; keeping what is stored (31h old) — re-read TopDeck.gg's API terms before the next run.",  # noqa: E501
    # §1.3 paused on 451, 451 again
    ("1.3", "451 again"): "topdeck: refused for legal reasons again (HTTP 451); still paused since 2026-10-05; keeping what is stored (31h old) — open topdeck.gg in your browser and read the notice there before the next run.",  # noqa: E501
    # §1.3 paused on 429, 429 again
    ("1.3", "429 again"): "topdeck: asked for a pause again (HTTP 429); still paused since 2026-10-05; keeping what is stored (31h old) — not before 14:03:10 UTC.",  # noqa: E501
    # §1.3 paused, every format unanswered
    ("1.3", "paused unanswered"): "topdeck: could not refresh (timed out); still paused since 2026-10-05; keeping what is stored (31h old).",  # noqa: E501
    # §1.3 paused, answered 401 while the cause is another
    ("1.3", "401 other"): "topdeck: the key was not accepted (HTTP 401); still paused since 2026-10-05; keeping what is stored (31h old) — set a working key with 'sensei-top config --set-topdeck-key KEY' before the next run.",  # noqa: E501
    # §1.3 paused, answered 403 while the cause is another
    ("1.3", "403 other"): "topdeck: refused (HTTP 403); still paused since 2026-10-05; keeping what is stored (31h old) — re-read TopDeck.gg's API terms before the next run.",  # noqa: E501
    # §1.3 paused, answered 451 while the cause is another
    ("1.3", "451 other"): "topdeck: refused for legal reasons (HTTP 451); still paused since 2026-10-05; keeping what is stored (31h old) — open topdeck.gg in your browser and read the notice there before the next run.",  # noqa: E501
    # §1.3 paused, answered 429 while the cause is another
    ("1.3", "429 other"): "topdeck: asked for a pause (HTTP 429); still paused since 2026-10-05; keeping what is stored (31h old) — not before 14:03:10 UTC.",  # noqa: E501
    # §1.3 the server's own attempt ends a wait
    ("1.3", "wait over"): "topdeck: 3 tournament events stored; the wait is over.",
}

# Q13.7's several-formats form (followup3.md:204), copied by script.
SEVERAL = "Standard and Pioneer; Modern and Legacy were not fetched"

H = 3600.0
WAITING = HoldStatus.WAITING
PAUSED = HoldStatus.PAUSED


def _t(hour: int, minute: int = 0, *, day: int = 5) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


# The answer arrives, and the line prints, at 14:10 on 2026-10-05 (UTC).
NOW = _t(14, 10)
# A hand run during a wait or a pause, later the same day.
LATER = _t(15, 0)
# A pause that began this morning: "since 2026-10-05".
PAUSED_SINCE = _t(9, 0)

EVENT = "event:standard-league-2026-10-03"
MONTH = "month:2026-09"
INDEX = "index"
# Where a run that had stored events was answered; no line names it.
LATER_EVENT = "event:standard-league-2026-10-04"

REASONS = {
    401: "HTTP 401 Unauthorized",
    403: "HTTP 403 Forbidden",
    404: "HTTP 404 Not Found",
    429: "HTTP 429 Too Many Requests",
    451: "HTTP 451 Unavailable For Legal Reasons",
    503: "HTTP 503 Service Unavailable",
}


def _hold(status: HoldStatus, cause: int, *, since: datetime, answers: int = 0,
          last_status: int | None = None, last_at: datetime | None = None,
          not_before: datetime | None = None, source: str = MTGO) -> Hold:
    return Hold(
        source=source, status=status, http_status=cause, answers=answers, since=since,
        last_status=last_status if last_status is not None else cause,
        last_at=last_at if last_at is not None else since, not_before=not_before,
    )


def _http(status: int, *, place: str = INDEX, ra: datetime | None = None,
          first: bool = True) -> Answer:
    return Answer(kind=answer_kind(status), reason=REASONS[status], at=NOW, http_status=status,
                  place=place, retry_after=ra, first_request=first)


TIMED_OUT = Answer(kind=AnswerKind.GENERIC, reason="timed out", at=NOW, place=INDEX)
NOT_FOUND = Answer(kind=AnswerKind.GENERIC, reason=REASONS[404], at=NOW, http_status=404,
                   place=INDEX)

_UNCHANGED = object()


def _result(*, status: str = "failed", before: Hold | None = None,
            after: Hold | object | None = _UNCHANGED, answer: Answer | None = None,
            events: int = 0, skipped: int = 0, age_h: float | None = 5,
            answered: tuple[str, ...] = (), unfetched: tuple[str, ...] = (),
            unanswered: tuple[str, ...] = ()) -> RefreshResult:
    """A hand run (``sensei-top meta``); ``_serve`` makes it the server's.
    ``after`` defaults to ``before``: a generic answer, a held run and a
    fresh one leave the hold as it was."""
    return RefreshResult(
        status=status, events=events, skipped=skipped,
        age_seconds=age_h * H if age_h is not None else None,
        hold_before=before, hold_after=before if after is _UNCHANGED else after,
        answer=answer, by_hand=True, answered=answered, unfetched=unfetched,
        unanswered=unanswered,
    )


def _serve(result: RefreshResult) -> RefreshResult:
    """The same run as ``serve``'s own attempt."""
    return replace(result, by_hand=False)


# The holds S3's transitions leave at NOW.
# A first 429: three hours from 14:10, with no Retry-After.
WAIT_429 = _hold(WAITING, 429, since=NOW, not_before=_t(17, 10))
# A first 503 whose Retry-After (17:10) is later than the hour's floor (15:10).
WAIT_503 = _hold(WAITING, 503, since=NOW, answers=1, not_before=_t(17, 10))
# The same after a page was read: the count restarts at 0 (k1).
WAIT_503_READ = _hold(WAITING, 503, since=NOW, answers=0, not_before=_t(17, 10))
# A wait whose not-before has passed, so the gate let the run through.
WAITED_429 = _hold(WAITING, 429, since=_t(10), not_before=_t(13))
WAITED_503 = _hold(WAITING, 503, since=_t(12), answers=1, not_before=_t(13))
# A second 429 in a row, its Retry-After 17:10: paused from now (Q13.5).
PAUSED_429_TWICE = _hold(PAUSED, 429, since=NOW, not_before=_t(17, 10))
# Two first-request 503s since 13:00 yesterday; the third, at NOW, is 25 h
# after the first, so the day rule pauses the source (Q13.4, k2).
DAY_BEFORE = _hold(WAITING, 503, since=_t(13, day=4), answers=2, last_at=_t(12),
                   not_before=_t(13))
DAY_PAUSED = _hold(PAUSED, 503, since=NOW, answers=3)
DAY_PAUSED_AHEAD = _hold(PAUSED, 503, since=NOW, answers=3, not_before=_t(17, 10))


def _paused(cause: int, *, not_before: datetime | None = None) -> Hold:
    """A pause standing since this morning, its cause's answer the latest."""
    return _hold(PAUSED, cause, since=PAUSED_SINCE, not_before=not_before)


def _paused_after(cause: int, answered: int, *, not_before: datetime | None = None) -> Hold:
    """The pause a hand run leaves: cause (or a refusal's new cause) and date
    kept (Q13.3, k3), the latest answer at NOW."""
    return _hold(PAUSED, cause, since=PAUSED_SINCE, last_status=answered, last_at=NOW,
                 not_before=not_before)


def _first_429(place: str, events: int = 0) -> RefreshResult:
    return _result(after=WAIT_429, answer=_http(429, place=place), events=events)


def _first_503(place: str = INDEX, events: int = 0, *, age_h: float | None = 5) -> RefreshResult:
    if events:
        return _result(after=WAIT_503_READ, answer=_http(503, place=place, ra=_t(17, 10),
                                                         first=False), events=events)
    return _result(after=WAIT_503, answer=_http(503, place=place, ra=_t(17, 10)), age_h=age_h)


def _refused(code: int, place: str, events: int = 0) -> RefreshResult:
    # From no hold, a refusal pauses from the moment it arrives (k4).
    after = _hold(PAUSED, code, since=NOW)
    return _result(after=after, answer=_http(code, place=place), events=events)


def _twice(place: str, events: int = 0) -> RefreshResult:
    return _result(before=WAITED_429, after=PAUSED_429_TWICE,
                   answer=_http(429, place=place, ra=_t(17, 10)), events=events, age_h=3)


def _hand(cause: int, answer: Answer, after: Hold | object | None = _UNCHANGED,
          events: int = 0) -> RefreshResult:
    """A hand run during a pause on ``cause``, the stored copy 31 h old."""
    return _result(before=_paused(cause), after=after, answer=answer, events=events, age_h=31)


# (catalog key, surface, now, result)
CASES = [
    (("1.1", "success"), "meta", NOW, _result(status="updated", events=4, skipped=2)),
    (("1.1", "fresh"), "meta", NOW, _result(status="fresh", age_h=1.2)),
    (("1.1", "generic"), "meta", NOW, _result(answer=TIMED_OUT)),
    (("1.1", "generic after"), "meta", NOW, _result(answer=TIMED_OUT, events=2)),
    (("1.1", "403 index"), "meta", NOW, _refused(403, INDEX)),
    (("1.1", "403 month"), "meta", NOW, _refused(403, MONTH)),
    (("1.1", "403 event"), "meta", NOW, _refused(403, EVENT)),
    (("1.1", "403 after"), "meta", NOW, _refused(403, LATER_EVENT, events=2)),
    (("1.1", "401 index"), "meta", NOW, _refused(401, INDEX)),
    (("1.1", "401 month"), "meta", NOW, _refused(401, MONTH)),
    (("1.1", "401 event"), "meta", NOW, _refused(401, EVENT)),
    (("1.1", "401 after"), "meta", NOW, _refused(401, LATER_EVENT, events=2)),
    (("1.1", "451 index"), "meta", NOW, _refused(451, INDEX)),
    (("1.1", "451 month"), "meta", NOW, _refused(451, MONTH)),
    (("1.1", "451 event"), "meta", NOW, _refused(451, EVENT)),
    (("1.1", "451 after"), "meta", NOW, _refused(451, LATER_EVENT, events=2)),
    (("1.1", "429 index"), "meta", NOW, _first_429(INDEX)),
    (("1.1", "429 month"), "meta", NOW, _first_429(MONTH)),
    (("1.1", "429 event"), "meta", NOW, _first_429(EVENT)),
    (("1.1", "429 after"), "meta", NOW, _first_429(LATER_EVENT, events=2)),
    (("1.1", "429 twice index"), "meta", NOW, _twice(INDEX)),
    (("1.1", "429 twice month"), "meta", NOW, _twice(MONTH)),
    (("1.1", "429 twice event"), "meta", NOW, _twice(EVENT)),
    (("1.1", "429 twice after"), "meta", NOW, _twice(LATER_EVENT, events=2)),
    (("1.1", "503"), "meta", NOW, _first_503()),
    (("1.1", "503 after"), "meta", NOW, _first_503(LATER_EVENT, events=2)),
    # The day rule's third first-request 503, with no Retry-After: no time.
    (("1.1", "503 day"), "meta", NOW,
     _result(before=DAY_BEFORE, after=DAY_PAUSED, answer=_http(503), age_h=26)),
    (("1.1", "503 day not before"), "meta", NOW,
     _result(before=DAY_BEFORE, after=DAY_PAUSED_AHEAD, answer=_http(503, ra=_t(17, 10)),
             age_h=26)),
    (("1.1", "wait over"), "meta", NOW,
     _result(status="updated", before=WAITED_503, after=None, events=4, skipped=2)),
    # A hand run the gate held: the hold printed is the one that held it.
    (("1.2", "waiting 503"), "meta", LATER,
     _result(status="held", before=_hold(WAITING, 503, since=_t(14, 10), answers=1,
                                         not_before=_t(17, 10)))),
    (("1.2", "waiting 429"), "meta", LATER,
     _result(status="held", before=_hold(WAITING, 429, since=_t(14, 10),
                                         not_before=_t(17, 10)))),
    # Printed at 23:50 on the 5th: the not-before is on the 6th, so both
    # times carry their dates.
    (("1.2", "waiting dated"), "meta", _t(23, 50),
     _result(status="held", before=_hold(WAITING, 503, since=_t(23, 40), answers=1,
                                         not_before=_t(16, day=6)))),
    # Paused on a 403 this morning; a 429 at 14:10 named 17:10.
    (("1.2", "paused ahead"), "meta", LATER,
     _result(status="held", before=_hold(PAUSED, 403, since=PAUSED_SINCE, last_status=429,
                                         last_at=_t(14, 10), not_before=_t(17, 10)))),
    (("1.2", "pause lifted"), "meta", NOW,
     _result(status="updated", before=_paused(403), after=None, events=4, skipped=2)),
    (("1.2", "403 again"), "meta", NOW, _hand(403, _http(403), _paused_after(403, 403))),
    (("1.2", "401 again"), "meta", NOW, _hand(401, _http(401), _paused_after(401, 401))),
    (("1.2", "451 again"), "meta", NOW, _hand(451, _http(451), _paused_after(451, 451))),
    # A bare 503 during a pause clears the not-before (lines.md §0).
    (("1.2", "503 again"), "meta", NOW, _hand(503, _http(503), _paused_after(503, 503))),
    (("1.2", "503 again not before"), "meta", NOW,
     _hand(503, _http(503, ra=_t(18, 10)), _paused_after(503, 503, not_before=_t(18, 10)))),
    (("1.2", "429 again"), "meta", NOW,
     _hand(429, _http(429, ra=_t(18, 10)), _paused_after(429, 429, not_before=_t(18, 10)))),
    # A refusal replaces the cause and keeps the date.
    (("1.2", "403 other"), "meta", NOW, _hand(429, _http(403), _paused_after(403, 403))),
    (("1.2", "401 other"), "meta", NOW, _hand(403, _http(401), _paused_after(401, 401))),
    (("1.2", "451 other"), "meta", NOW, _hand(403, _http(451), _paused_after(451, 451))),
    # A 503 or a 429 keeps the cause.
    (("1.2", "503 other"), "meta", NOW, _hand(403, _http(503), _paused_after(403, 503))),
    (("1.2", "503 other not before"), "meta", NOW,
     _hand(429, _http(503, ra=_t(18, 10)), _paused_after(429, 503, not_before=_t(18, 10)))),
    (("1.2", "429 other"), "meta", NOW,
     _hand(503, _http(429, ra=_t(18, 10)), _paused_after(503, 429, not_before=_t(18, 10)))),
    (("1.2", "generic"), "meta", NOW, _hand(403, TIMED_OUT)),
    (("1.2", "generic http"), "meta", NOW, _hand(403, NOT_FOUND)),
    (("1.2", "403 again after"), "meta", NOW,
     _hand(403, _http(403, place=LATER_EVENT), _paused_after(403, 403), events=2)),
    (("1.2", "generic after"), "meta", NOW, _hand(403, TIMED_OUT, events=2)),
    # serve's own attempts, each moving the hold into a wait.
    (("1.4", "429 index"), "serve", NOW, _serve(_first_429(INDEX))),
    (("1.4", "429 month"), "serve", NOW, _serve(_first_429(MONTH))),
    (("1.4", "429 event"), "serve", NOW, _serve(_first_429(EVENT))),
    (("1.4", "429 after"), "serve", NOW, _serve(_first_429(LATER_EVENT, events=2))),
    (("1.4", "503"), "serve", NOW, _serve(_first_503())),
    (("1.4", "503 after"), "serve", NOW, _serve(_first_503(LATER_EVENT, events=2))),
]


@pytest.mark.parametrize(("key", "surface", "now", "result"), CASES,
                         ids=[" ".join(case[0]) for case in CASES])
def test_each_catalog_entry_renders_exactly(key, surface, now, result):
    assert render("mtgo", result, surface=surface, now=now) == [LINES[key]]


def test_every_catalog_entry_has_a_case():
    assert sorted(case[0] for case in CASES) == sorted(LINES)


@pytest.mark.parametrize(
    ("result", "why"),
    [
        (_serve(_result(before=WAITED_503, after=replace(WAITED_503, answers=2, last_at=NOW,
                                                         not_before=_t(17, 10)),
                        answer=_http(503, ra=_t(17, 10)))),
         "a repeated 503: the not-before moved, the hold did not"),
        (_serve(_result(answer=TIMED_OUT)), "a generic failure"),
        (_serve(_result(before=WAITED_429, answer=TIMED_OUT)), "a generic failure during a wait"),
        (_serve(_result(status="updated", events=4, skipped=2)), "an ordinary success"),
        (_serve(_result(status="held", before=WAIT_429)), "no attempt: the gate held it"),
        (_serve(_result(status="fresh", age_h=1.2)), "no attempt: the copy is fresh"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_serve_is_silent_when_the_hold_did_not_move(result, why):
    assert render("mtgo", result, surface="serve", now=NOW) == []


@pytest.mark.parametrize(
    ("key", "result"),
    [
        (("1.1", "403 index"), _serve(_refused(403, INDEX))),       # into a pause
        (("1.1", "429 twice index"), _serve(_twice(INDEX))),        # waiting to paused
        (("1.1", "503 day"),                                        # waiting to paused
         _serve(_result(before=DAY_BEFORE, after=DAY_PAUSED, answer=_http(503), age_h=26))),
        (("1.1", "wait over"),                                      # the end of a wait
         _serve(_result(status="updated", before=WAITED_503, after=None, events=4,
                        skipped=2))),
        # A change of cause: a 503 after a 429's wait ran out.
        (("1.4", "503"), _serve(_result(before=WAITED_429, after=WAIT_503,
                                        answer=_http(503, ra=_t(17, 10))))),
    ],
    ids=lambda v: " ".join(v) if isinstance(v, tuple) else None,
)
def test_serve_prints_on_every_other_transition(key, result):
    """lines.md §1.4: every other line serve prints is the meta line."""
    assert render("mtgo", result, surface="serve", now=NOW) == [LINES[key]]


def test_meta_prints_the_repeated_503_serve_keeps_quiet():
    result = _result(before=WAITED_503, after=replace(WAITED_503, answers=2, last_at=NOW,
                                                      not_before=_t(17, 10)),
                     answer=_http(503, ra=_t(17, 10)))
    assert render("mtgo", result, surface="meta", now=NOW) == [LINES["1.1", "503"]]


@pytest.mark.parametrize("surface", ["meta", "serve"])
def test_no_stored_copy_reads_no_cached_copy(surface):
    """The 503 entries' label: ``(no cached copy)`` when none."""
    key = ("1.1" if surface == "meta" else "1.4", "503")
    expected = LINES[key].replace("(5h old)", "(no cached copy)")
    result = replace(_first_503(age_h=None), by_hand=surface == "meta")
    assert render("mtgo", result, surface=surface, now=NOW) == [expected]


def test_paused_ahead_names_the_503_that_set_the_time():
    """The (l) line's label: "HTTP 503" in place of "HTTP 429" when a 503 set
    the time."""
    hold = _hold(PAUSED, 403, since=PAUSED_SINCE, last_status=503, last_at=_t(14, 10),
                 not_before=_t(17, 10))
    expected = LINES["1.2", "paused ahead"].replace("HTTP 429", "HTTP 503")
    assert render("mtgo", _result(status="held", before=hold), surface="meta",
                  now=LATER) == [expected]


def test_both_times_are_dated_when_only_the_answer_is_on_another_date():
    """The date rule, from the other side of midnight: printed at 00:10 on
    the 6th, the answer (23:40 on the 5th) needs its date, so the not-before
    takes its own."""
    hold = _hold(WAITING, 503, since=_t(23, 40), answers=1, not_before=_t(16, day=6))
    assert render("mtgo", _result(status="held", before=hold), surface="meta",
                  now=_t(0, 10, day=6)) == [LINES["1.2", "waiting dated"]]


def test_a_single_time_on_another_date_carries_it():
    """A first 429 at 22:30: three hours on is 01:30 on the 6th."""
    late = _t(22, 30)
    hold = _hold(WAITING, 429, since=late, not_before=_t(1, 30, day=6))
    result = _result(after=hold, answer=replace(_http(429), at=late))
    expected = LINES["1.1", "429 index"].replace("17:10 UTC", "2026-10-06 01:30 UTC")
    assert render("mtgo", result, surface="meta", now=late) == [expected]


def test_a_not_before_off_the_minute_prints_rounded_up():
    """Never a time earlier than the one stored."""
    hold = replace(WAIT_429, not_before=datetime(2026, 10, 5, 17, 9, 30, tzinfo=UTC))
    result = _result(after=hold, answer=_http(429))
    assert render("mtgo", result, surface="meta", now=NOW) == [LINES["1.1", "429 index"]]


HAND_RUN_ANSWERS = [
    case for case in CASES
    if case[0][0] == "1.2" and case[3].answer is not None and case[3].events == 0
]
_KEPT = "; still paused since 2026-10-05; keeping what is stored (31h old)"
_AFTER_N = " after 2 tournament events stored; keeping those; still paused since 2026-10-05"


@pytest.mark.parametrize(("key", "surface", "now", "result"), HAND_RUN_ANSWERS,
                         ids=[" ".join(case[0]) for case in HAND_RUN_ANSWERS])
def test_every_hand_run_answer_takes_its_after_n_form(key, surface, now, result):
    """followup4.md:83-88: drop "keeping what is stored (31h old)", put
    "after 2 tournament events stored; keeping those" after the status
    phrase, keep the tail. The catalog's two after-N hand-run entries are
    this rule applied to "403 again" and "generic"."""
    expected = LINES[key].replace(_KEPT, _AFTER_N)
    assert expected != LINES[key]
    assert render("mtgo", replace(result, events=2), surface=surface, now=now) == [expected]


def test_a_source_with_no_lines_is_refused():
    """fbettega's ``cache: …`` lines stay in cli.py."""
    with pytest.raises(ValueError, match="fbettega"):
        render("fbettega", _result(status="updated"), surface="meta", now=NOW)


# TopDeck (§1.3). The catalog's examples: Standard answered with 3 tournament
# events and Modern was next; a 429 at 14:02:28 whose retryAfterSeconds was
# 42, so its not-before is 14:03:10, to the second (D18); a stored copy 24h
# old, and 31h for a hand run during a pause, as §1.2's.
STANDARD = "Standard"
MODERN = "Modern"
PIONEER = "Pioneer"
LEGACY = "Legacy"


def _s(hour: int, minute: int, second: int, *, day: int = 5) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=UTC)


TD_NOW = _s(14, 2, 28)
TD_WAIT_S = 42.0
TD_NOT_BEFORE = _s(14, 3, 10)
# A hand run during the wait, before its not-before.
TD_LATER = _s(14, 2, 40)


def _td_http(status: int, place: str = STANDARD, *, seconds: float | None = None,
             at: datetime = TD_NOW) -> Answer:
    """TopDeck's answer at ``place``, a format. A 429 that names its wait
    names it in the body and in ``Retry-After`` alike, as TopDeck's API does."""
    ra = at + timedelta(seconds=seconds) if seconds is not None else None
    return Answer(kind=answer_kind(status), reason=REASONS[status], at=at, http_status=status,
                  place=place, retry_after=ra, retry_after_s=seconds)


TD_TIMED_OUT = Answer(kind=AnswerKind.GENERIC, reason="timed out", at=TD_NOW)

# The holds S3's transitions leave at TD_NOW. TopDeck holds no 503.
# A first 429: TopDeck's own 42 s.
TD_WAIT = _hold(WAITING, 429, since=TD_NOW, not_before=TD_NOT_BEFORE, source=TOPDECK)
# A wait whose not-before has passed, so the gate let the run through.
TD_WAITED = _hold(WAITING, 429, since=_s(13, 0, 0), not_before=_s(13, 0, 42), source=TOPDECK)
# A second 429 in a row: paused from now, not before its own 42 s (Q13.5).
TD_TWICE = _hold(PAUSED, 429, since=TD_NOW, not_before=TD_NOT_BEFORE, source=TOPDECK)


def _td_stopped(status: int, after: Hold, *, before: Hold | None = None,
                fetched: bool = False) -> RefreshResult:
    """A run TopDeck stopped with ``status``: at Standard with Modern left
    unasked, or, once ``fetched``, at Modern after Standard's 3 events."""
    seconds = TD_WAIT_S if status == 429 else None
    if fetched:
        answer = _td_http(status, MODERN, seconds=seconds)
        return _result(before=before, after=after, answer=answer, events=3, age_h=24,
                       answered=(STANDARD,))
    return _result(before=before, after=after, answer=_td_http(status, seconds=seconds),
                   age_h=24, unfetched=(MODERN,))


def _td_refused(code: int, *, fetched: bool = False) -> RefreshResult:
    # From no hold, a refusal pauses from the moment it arrives (k4).
    return _td_stopped(code, _hold(PAUSED, code, since=TD_NOW, source=TOPDECK), fetched=fetched)


def _td_paused(cause: int, *, last_status: int | None = None, last_at: datetime | None = None,
               not_before: datetime | None = None) -> Hold:
    """A pause standing since this morning."""
    return _hold(PAUSED, cause, since=PAUSED_SINCE, last_status=last_status, last_at=last_at,
                 not_before=not_before, source=TOPDECK)


def _td_paused_after(cause: int, answered: int, *, not_before: datetime | None = None) -> Hold:
    """The pause a hand run leaves: cause (or a refusal's new cause) and date
    kept (Q13.3, k3), the latest answer at TD_NOW."""
    return _td_paused(cause, last_status=answered, last_at=TD_NOW, not_before=not_before)


def _td_hand(cause: int, answer: Answer, after: Hold | object | None = _UNCHANGED
             ) -> RefreshResult:
    """A hand run during a pause on ``cause``, the stored copy 31h old: answered
    at Standard with Modern unasked, or with neither format answering."""
    if answer.kind == AnswerKind.GENERIC:
        return _result(before=_td_paused(cause), answer=answer, age_h=31,
                       unanswered=(STANDARD, MODERN))
    return _result(before=_td_paused(cause), after=after, answer=answer, age_h=31,
                   unfetched=(MODERN,))


def _td_success(before: Hold | None = None, *, unanswered: tuple[str, ...] = (),
                skipped: int = 0) -> RefreshResult:
    """A run that completed: Standard's 3 events stored, and Modern's too
    unless it went unanswered. A completed run lifts the hold (k6)."""
    answered = (STANDARD,) if unanswered else (STANDARD, MODERN)
    return _result(status="updated", before=before, after=None, events=3, skipped=skipped,
                   answered=answered, unanswered=unanswered)


# (catalog key, surface, now, result)
TOPDECK_CASES = [
    (("1.3", "success"), "meta", TD_NOW, _td_success()),
    (("1.3", "unanswered"), "meta", TD_NOW, _td_success(unanswered=(MODERN,))),
    (("1.3", "all unanswered"), "meta", TD_NOW,
     _result(answer=TD_TIMED_OUT, age_h=24, unanswered=(STANDARD, MODERN))),
    (("1.3", "no key"), "meta", TD_NOW, _result(status="not_configured", age_h=None)),
    (("1.3", "401"), "meta", TD_NOW, _td_refused(401)),
    (("1.3", "401 after"), "meta", TD_NOW, _td_refused(401, fetched=True)),
    (("1.3", "403 after"), "meta", TD_NOW, _td_refused(403, fetched=True)),
    (("1.3", "403 at"), "meta", TD_NOW, _td_refused(403)),
    (("1.3", "451 at"), "meta", TD_NOW, _td_refused(451)),
    (("1.3", "451 after"), "meta", TD_NOW, _td_refused(451, fetched=True)),
    (("1.3", "429 after"), "meta", TD_NOW, _td_stopped(429, TD_WAIT, fetched=True)),
    (("1.3", "429 at"), "meta", TD_NOW, _td_stopped(429, TD_WAIT)),
    (("1.3", "429 twice at"), "meta", TD_NOW, _td_stopped(429, TD_TWICE, before=TD_WAITED)),
    (("1.3", "429 twice after"), "meta", TD_NOW,
     _td_stopped(429, TD_TWICE, before=TD_WAITED, fetched=True)),
    # A hand run the gate held: the hold printed is the one that held it.
    (("1.3", "waiting"), "meta", TD_LATER, _result(status="held", before=TD_WAIT, age_h=24)),
    # Paused on a 403 this morning; a 429 at 14:02:28 named 42 s.
    (("1.3", "paused ahead"), "meta", TD_LATER,
     _result(status="held", before=_td_paused(403, last_status=429, last_at=TD_NOW,
                                              not_before=TD_NOT_BEFORE), age_h=24)),
    (("1.3", "pause lifted"), "meta", TD_NOW, _td_success(_td_paused(403))),
    (("1.3", "401 again"), "meta", TD_NOW,
     _td_hand(401, _td_http(401), _td_paused_after(401, 401))),
    (("1.3", "403 again"), "meta", TD_NOW,
     _td_hand(403, _td_http(403), _td_paused_after(403, 403))),
    (("1.3", "451 again"), "meta", TD_NOW,
     _td_hand(451, _td_http(451), _td_paused_after(451, 451))),
    (("1.3", "429 again"), "meta", TD_NOW,
     _td_hand(429, _td_http(429, seconds=TD_WAIT_S),
              _td_paused_after(429, 429, not_before=TD_NOT_BEFORE))),
    (("1.3", "paused unanswered"), "meta", TD_NOW, _td_hand(403, TD_TIMED_OUT)),
    # A refusal replaces the cause and keeps the date.
    (("1.3", "401 other"), "meta", TD_NOW,
     _td_hand(403, _td_http(401), _td_paused_after(401, 401))),
    (("1.3", "403 other"), "meta", TD_NOW,
     _td_hand(429, _td_http(403), _td_paused_after(403, 403))),
    (("1.3", "451 other"), "meta", TD_NOW,
     _td_hand(403, _td_http(451), _td_paused_after(451, 451))),
    # A 429 keeps the cause.
    (("1.3", "429 other"), "meta", TD_NOW,
     _td_hand(403, _td_http(429, seconds=TD_WAIT_S),
              _td_paused_after(403, 429, not_before=TD_NOT_BEFORE))),
    (("1.3", "wait over"), "serve", TD_NOW, _serve(_td_success(TD_WAITED))),
]
TD_CASE = {case[0]: case for case in TOPDECK_CASES}

# The lines printed ahead of an entry's own: "no answer for" follows the
# success line, as cli.py has always printed it (S3, "as today").
TD_AHEAD = {("1.3", "unanswered"): [TOPDECK_LINES["1.3", "success"]]}


@pytest.mark.parametrize(("key", "surface", "now", "result"), TOPDECK_CASES,
                         ids=[" ".join(case[0]) for case in TOPDECK_CASES])
def test_each_topdeck_entry_renders_exactly(key, surface, now, result):
    expected = [*TD_AHEAD.get(key, []), TOPDECK_LINES[key]]
    assert render("topdeck", result, surface=surface, now=now) == expected


def test_every_topdeck_entry_has_a_case():
    assert sorted(case[0] for case in TOPDECK_CASES) == sorted(TOPDECK_LINES)


def test_every_serve_case_is_the_servers_own_attempt():
    assert all(not case[3].by_hand for case in (*CASES, *TOPDECK_CASES) if case[1] == "serve")


@pytest.mark.parametrize(
    ("result", "why"),
    [
        (_serve(_td_success()), "an ordinary success"),
        (_serve(_td_success(unanswered=(MODERN,))), "a success with a format unanswered"),
        (_serve(_result(answer=TD_TIMED_OUT, age_h=24, unanswered=(STANDARD, MODERN))),
         "every format unanswered"),
        (_serve(_result(before=TD_WAITED, answer=TD_TIMED_OUT, age_h=24,
                        unanswered=(STANDARD, MODERN))),
         "every format unanswered during a wait"),
        (_serve(_result(status="held", before=TD_WAIT, age_h=24)),
         "no attempt: the gate held it"),
        (_serve(_result(status="fresh", age_h=5)), "no attempt: the copy is fresh"),
        (_serve(_result(status="not_configured", age_h=None)), "no attempt: no key"),
    ],
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_serve_is_silent_for_topdeck_when_the_hold_did_not_move(result, why):
    assert render("topdeck", result, surface="serve", now=TD_NOW) == []


@pytest.mark.parametrize(
    ("key", "result"),
    [
        *[(key, TD_CASE[key][3]) for key in [
            ("1.3", "401"), ("1.3", "401 after"), ("1.3", "403 at"),            # into a pause
            ("1.3", "451 after"),
            ("1.3", "429 at"), ("1.3", "429 after"),                            # into a wait
            ("1.3", "429 twice at"), ("1.3", "429 twice after"),          # waiting to paused
        ]],
        # A change of cause: a 403 after a 429's wait ran out.
        (("1.3", "403 at"), _td_stopped(403, _hold(PAUSED, 403, since=TD_NOW, source=TOPDECK),
                                        before=TD_WAITED)),
    ],
    ids=lambda v: " ".join(v) if isinstance(v, tuple) else None,
)
def test_topdeck_prints_the_same_line_on_serve(key, result):
    """S3: TopDeck's lines are the same on both surfaces."""
    assert render("topdeck", _serve(result), surface="serve", now=TD_NOW) == [TOPDECK_LINES[key]]


# Every §1.3 hand-run answer but the generic one: a run where every format
# went unanswered stored nothing.
TD_HAND_RUN_ANSWERS = [
    case for case in TOPDECK_CASES
    if case[3].hold_before is not None and case[3].hold_before.status == PAUSED
    and case[3].answer is not None and case[3].answer.kind != AnswerKind.GENERIC
]
_TD_AFTER_N = " after 3 tournament events stored; keeping those; still paused since 2026-10-05"


@pytest.mark.parametrize(("key", "surface", "now", "result"), TD_HAND_RUN_ANSWERS,
                         ids=[" ".join(case[0]) for case in TD_HAND_RUN_ANSWERS])
def test_every_topdeck_hand_run_answer_takes_its_after_n_form(key, surface, now, result):
    """§0's after-N rule, which composes with every hand-run line
    (followup4.md:85-88): Standard's 3 events stored, then Modern answered."""
    expected = TOPDECK_LINES[key].replace(_KEPT, _TD_AFTER_N)
    assert expected != TOPDECK_LINES[key]
    result = replace(result, events=3, answered=(STANDARD,), unfetched=(),
                     answer=replace(result.answer, place=MODERN))
    assert render("topdeck", result, surface=surface, now=now) == [expected]


@pytest.mark.parametrize(
    ("key", "before", "surface"),
    [(("1.3", "pause lifted"), _td_paused(403), "meta"),
     (("1.3", "wait over"), TD_WAITED, "serve")],
    ids=["pause lifted", "wait over"],
)
def test_no_answer_follows_the_line_that_lifts_the_hold(key, before, surface):
    """k6 (followup4.md:256-262): the "no answer for" line after the lifted
    line is "the existing per-format handling doing its job"."""
    result = replace(_td_success(before, unanswered=(MODERN,)), by_hand=surface == "meta")
    assert render("topdeck", result, surface=surface, now=TD_NOW) == [
        TOPDECK_LINES[key], TOPDECK_LINES["1.3", "unanswered"]
    ]


def test_a_429_that_names_no_wait_prints_none():
    """Q13.7: "(HTTP 429)" without ", 42 s" when the wait is the app's own
    hour."""
    hold = replace(TD_WAIT, not_before=TD_NOW + timedelta(hours=1))
    result = _result(after=hold, answer=_td_http(429), age_h=24, unfetched=(MODERN,))
    expected = (TOPDECK_LINES["1.3", "429 at"].replace(", 42 s", "")
                .replace("14:03:10 UTC", "15:02:28 UTC"))
    assert render("topdeck", result, surface="meta", now=TD_NOW) == [expected]


def test_a_429_whose_wait_is_only_in_the_header_names_it():
    answer = replace(_td_http(429, seconds=TD_WAIT_S), retry_after_s=None)
    assert answer.retry_after == TD_NOT_BEFORE
    result = _result(after=TD_WAIT, answer=answer, age_h=24, unfetched=(MODERN,))
    assert render("topdeck", result, surface="meta", now=TD_NOW) == [
        TOPDECK_LINES["1.3", "429 at"]
    ]


@pytest.mark.parametrize("name", ["403 after", "429 after"])
def test_several_formats_on_each_side(name):
    """Q13.7: "Standard and Pioneer; Modern and Legacy were not fetched", and
    the hint names every format not fetched."""
    _, _, now, case = TD_CASE["1.3", name]
    result = replace(case, answered=(STANDARD, PIONEER), unfetched=(LEGACY,))
    expected = (TOPDECK_LINES["1.3", name].replace("Standard; Modern was not fetched", SEVERAL)
                .replace("--format Modern'", "--format Modern --format Legacy'"))
    assert render("topdeck", result, surface="meta", now=now) == [expected]


def test_a_format_left_unanswered_before_the_answer_was_not_fetched():
    """Pioneer timed out between Standard and Modern's 429: the run did not
    get it either, so the line names it with Modern, and so does the hint."""
    _, _, now, case = TD_CASE["1.3", "429 after"]
    result = replace(case, unanswered=(PIONEER,))
    several = SEVERAL.removeprefix("Standard and Pioneer; ").replace("Modern and Legacy",
                                                                     "Pioneer and Modern")
    expected = (TOPDECK_LINES["1.3", "429 after"].replace("Modern was not fetched", several)
                .replace("--format Modern'", "--format Pioneer --format Modern'"))
    assert render("topdeck", result, surface="meta", now=now) == [expected]


def test_a_format_left_unanswered_before_a_first_answer_keeps_the_at_form():
    """Nothing fetched: the line names where the run stopped, and the hint is
    the plain command, which asks for every format again."""
    case = _td_stopped(429, TD_WAIT)
    result = replace(case, answer=replace(case.answer, place=MODERN), unanswered=(STANDARD,),
                     unfetched=())
    expected = TOPDECK_LINES["1.3", "429 at"].replace("at Standard", "at Modern")
    assert render("topdeck", result, surface="meta", now=TD_NOW) == [expected]


def test_a_topdeck_time_on_another_date_carries_it():
    """§0's date rule, to the second: 42 s after 23:59:50 is 00:00:32 on the
    6th."""
    late = _s(23, 59, 50)
    hold = replace(TD_WAIT, since=late, not_before=_s(0, 0, 32, day=6))
    result = _result(after=hold, answer=_td_http(429, seconds=TD_WAIT_S, at=late), age_h=24,
                     unfetched=(MODERN,))
    expected = TOPDECK_LINES["1.3", "429 at"].replace("14:03:10 UTC", "2026-10-06 00:00:32 UTC")
    assert render("topdeck", result, surface="meta", now=late) == [expected]


def test_a_topdeck_wait_off_the_second_prints_rounded_up():
    """Never a time or a wait shorter than TopDeck's: 41.4 s from 14:02:28."""
    hold = replace(TD_WAIT, not_before=TD_NOW + timedelta(seconds=41.4))
    result = _result(after=hold, answer=_td_http(429, seconds=41.4), age_h=24,
                     unfetched=(MODERN,))
    assert render("topdeck", result, surface="meta", now=TD_NOW) == [
        TOPDECK_LINES["1.3", "429 at"]
    ]


def test_several_formats_unanswered_are_listed_as_cli_py_listed_them():
    """S3, "as today": cli.py printed the error's formats, ", "-joined, and
    a ``--format`` for each."""
    result = _td_success(unanswered=(PIONEER, MODERN))
    expected = (TOPDECK_LINES["1.3", "unanswered"].replace("for Modern;", "for Pioneer, Modern;")
                .replace("--format Modern'", "--format Pioneer --format Modern'"))
    assert render("topdeck", result, surface="meta", now=TD_NOW) == [
        TOPDECK_LINES["1.3", "success"], expected
    ]


@pytest.mark.parametrize(
    ("key", "before"),
    [(("1.3", "success"), None), (("1.3", "pause lifted"), _td_paused(403)),
     (("1.3", "wait over"), TD_WAITED)],
    ids=["success", "pause lifted", "wait over"],
)
def test_skipped_events_are_counted_as_cli_py_counted_them(key, before):
    """cli.py:507-508, the success entry's source: ", 2 skipped" after the
    count, as mtgo.com's success line has it."""
    skipped = LINES["1.1", "success"].removeprefix("mtgo: 4 tournament events stored")[:-1]
    expected = TOPDECK_LINES[key].replace("events stored", "events stored" + skipped)
    result = _td_success(before, skipped=2)
    assert render("topdeck", result, surface="meta", now=TD_NOW) == [expected]


def test_topdeck_fresh_prints_as_cli_py_printed_it():
    """Not in the catalog; S3 keeps TopDeck's lines "as today", and cli.py
    printed TopDeck's fresh line with the age to a whole hour, where
    mtgo.com's has a tenth."""
    expected = LINES["1.1", "fresh"].replace("mtgo:", "topdeck:").replace("1.2h", "5h")
    result = _result(status="fresh", age_h=5)
    assert render("topdeck", result, surface="meta", now=TD_NOW) == [expected]


@pytest.mark.parametrize("name", ["all unanswered", "429 twice at"])
def test_topdeck_with_no_stored_copy_reads_no_cached_copy(name):
    _, surface, now, case = TD_CASE["1.3", name]
    expected = TOPDECK_LINES["1.3", name].replace("(24h old)", "(no cached copy)")
    result = replace(case, age_seconds=None)
    assert render("topdeck", result, surface=surface, now=now) == [expected]


def test_a_topdeck_503_is_never_an_answer():
    """S5: TopDeck's 5xx is "no answer for" its format, never a hold."""
    result = _result(answer=_td_http(503), age_h=24, unfetched=(MODERN,))
    with pytest.raises(ValueError, match="no answer for"):
        render("topdeck", result, surface="meta", now=TD_NOW)
