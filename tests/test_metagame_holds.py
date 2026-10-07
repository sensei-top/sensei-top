"""The fetch holds (plan 14, S3): every transition of ``apply_outcome`` for
mtgo.com and TopDeck, every row of the gate, ``Retry-After``'s two forms,
``ceil_min`` and ``visible``.

No network. Every expected value is worked out by hand from S3's rules; the
times are written out in full, as SQLite stores them, so each assertion can be
checked against the rule it names without running anything. Holds are seeded
with SQL, not with ``apply_outcome``, so a transition is tested from a state
the rules describe rather than one the code produced.
"""

import urllib.error
from datetime import UTC, datetime, timedelta

import pytest

from sensei_top.db import open_database
from sensei_top.metagame.holds import (
    Gate,
    Hold,
    HoldStatus,
    apply_outcome,
    ceil_min,
    gate,
    parse_retry_after,
    read_hold,
    visible,
)
from sensei_top.metagame.source import (
    Answer,
    AnswerKind,
    RefreshResult,
    answer_kind,
    answer_reason,
)

# A run at 12:00:30 UTC: the half minute makes every ceil_min visible.
NOW = datetime(2026, 10, 5, 12, 0, 30, tzinfo=UTC)
NOW_S = "2026-10-05T12:00:30Z"


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "h.db")
    yield c
    c.close()


def _t(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _seed(conn, source, status, cause, *, answers=0, since="2026-10-04T09:00:00Z",
          not_before=None, last_status=None, last_at=None) -> Hold:
    conn.execute(
        "INSERT INTO meta_fetch_hold (source, status, http_status, answers, since, "
        "last_status, last_at, not_before) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (source, status, cause, answers, since,
         last_status if last_status is not None else cause,
         last_at if last_at is not None else since, not_before),
    )
    hold = read_hold(conn, source)
    assert hold is not None
    return hold


def _stored(conn, source="mtgo"):
    row = conn.execute(
        "SELECT status, http_status, answers, since, last_status, last_at, not_before "
        "FROM meta_fetch_hold WHERE source = ?",
        (source,),
    ).fetchone()
    if row is None:
        return None
    keys = ("status", "http_status", "answers", "since", "last_status", "last_at",
            "not_before")
    return dict(zip(keys, tuple(row), strict=True))


def _answer(kind, status, *, ra=None, ra_s=None, first=True, at=NOW) -> Answer:
    return Answer(kind=kind, reason=f"HTTP {status}", at=at, http_status=status,
                  place="index", retry_after=ra, retry_after_s=ra_s, first_request=first)


def _apply(conn, source, before, answer, *, page_read=False, completed=False, now=NOW):
    return apply_outcome(conn, source, before=before, answer=answer, page_read=page_read,
                         completed=completed, now=now)


def _hold(status, *, not_before=None, cause=429) -> Hold:
    return Hold(source="mtgo", status=HoldStatus(status), http_status=cause, answers=0,
                since=NOW - timedelta(hours=2), last_status=cause,
                last_at=NOW - timedelta(hours=2), not_before=not_before)


def _refused(status=403, **kw) -> Answer:
    return _answer(AnswerKind.REFUSED, status, **kw)


def _rate(**kw) -> Answer:
    return _answer(AnswerKind.RATE, 429, **kw)


def _unavailable(**kw) -> Answer:
    return _answer(AnswerKind.UNAVAILABLE, 503, **kw)


# ceil_min, visible, Retry-After


@pytest.mark.parametrize(
    ("t", "expected"),
    [
        (datetime(2026, 10, 5, 12, 0, 0, tzinfo=UTC), datetime(2026, 10, 5, 12, 0, tzinfo=UTC)),
        (datetime(2026, 10, 5, 12, 0, 0, 1, tzinfo=UTC), datetime(2026, 10, 5, 12, 1, tzinfo=UTC)),
        (datetime(2026, 10, 5, 12, 0, 59, tzinfo=UTC), datetime(2026, 10, 5, 12, 1, tzinfo=UTC)),
        (datetime(2026, 10, 5, 23, 59, 1, tzinfo=UTC), datetime(2026, 10, 6, 0, 0, tzinfo=UTC)),
    ],
)
def test_ceil_min_rounds_up_to_the_minute(t, expected):
    assert ceil_min(t) == expected


@pytest.mark.parametrize(
    ("hold", "expected"),
    [
        (None, False),
        (_hold("waiting", not_before=NOW + timedelta(minutes=1)), True),
        (_hold("waiting", not_before=NOW), False),
        (_hold("waiting", not_before=NOW - timedelta(minutes=1)), False),
        (_hold("waiting", not_before=None), False),
        (_hold("paused", not_before=None, cause=403), True),
        (_hold("paused", not_before=NOW - timedelta(hours=1)), True),
        (_hold("paused", not_before=NOW + timedelta(hours=1)), True),
    ],
)
def test_visible_is_a_pause_or_a_wait_still_ahead(hold, expected):
    assert visible(hold, NOW) is expected


def test_retry_after_delta_seconds_counts_from_the_response():
    assert parse_retry_after("120", at=NOW) == datetime(2026, 10, 5, 12, 2, 30, tzinfo=UTC)


def test_retry_after_http_date_is_an_aware_utc_time():
    parsed = parse_retry_after("Mon, 05 Oct 2026 15:30:00 GMT", at=NOW)
    assert parsed == datetime(2026, 10, 5, 15, 30, tzinfo=UTC)
    assert parsed.tzinfo is not None


@pytest.mark.parametrize("value", ["soon", "-5", "1.5", "Mon, 99 Foo 2026"])
def test_unparsable_retry_after_counts_as_absent_with_a_warning(value, caplog):
    with caplog.at_level("WARNING", logger="sensei_top.metagame.holds"):
        assert parse_retry_after(value, at=NOW) is None
    assert any("Retry-After" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_absent_retry_after_is_none_without_a_warning(value, caplog):
    with caplog.at_level("WARNING", logger="sensei_top.metagame.holds"):
        assert parse_retry_after(value, at=NOW) is None
    assert caplog.records == []


# The gate


@pytest.mark.parametrize(
    ("hold", "loop", "hand"),
    [
        # none, or waiting with not_before <= now: the freshness rule
        (None, Gate.FRESHNESS, Gate.FRESHNESS),
        (_hold("waiting", not_before=NOW), Gate.FRESHNESS, Gate.FRESHNESS),
        (_hold("waiting", not_before=NOW - timedelta(minutes=5)), Gate.FRESHNESS,
         Gate.FRESHNESS),
        # a NULL not-before has no time ahead
        (_hold("waiting", not_before=None), Gate.FRESHNESS, Gate.FRESHNESS),
        # waiting with not_before > now: no attempt
        (_hold("waiting", not_before=NOW + timedelta(seconds=1)), Gate.HELD, Gate.HELD),
        # paused with not_before > now: no attempt
        (_hold("paused", not_before=NOW + timedelta(minutes=30)), Gate.HELD, Gate.HELD),
        # paused otherwise: the loop makes no attempt, a hand run one ordinary run
        (_hold("paused", not_before=None, cause=403), Gate.HELD, Gate.RUN),
        (_hold("paused", not_before=NOW), Gate.HELD, Gate.RUN),
        (_hold("paused", not_before=NOW - timedelta(hours=1)), Gate.HELD, Gate.RUN),
    ],
)
def test_gate(hold, loop, hand):
    assert gate(hold, now=NOW, by_hand=False) == loop
    assert gate(hold, now=NOW, by_hand=True) == hand


# mtgo.com: the run completed


@pytest.mark.parametrize(
    "seed",
    [
        None,
        ("waiting", 429, 0, "2026-10-05T13:00:00Z"),
        ("waiting", 503, 2, "2026-10-05T12:30:00Z"),
        ("paused", 403, 0, None),
        ("paused", 503, 4, None),
    ],
)
def test_mtgo_a_completed_run_deletes_the_hold_and_stamps_nothing(conn, seed):
    before = None
    if seed is not None:
        status, cause, answers, nb = seed
        before = _seed(conn, "mtgo", status, cause, answers=answers, not_before=nb)
    assert _apply(conn, "mtgo", before, None, page_read=True, completed=True) is None
    assert _stored(conn) is None
    # Stamping meta_fetch_source is the fetcher's, never this module's.
    assert conn.execute("SELECT COUNT(*) FROM meta_fetch_source").fetchone()[0] == 0


def test_no_attempt_leaves_the_hold_as_it_was(conn):
    before = _seed(conn, "mtgo", "waiting", 429, not_before="2026-10-05T15:00:00Z")
    row = _stored(conn)
    assert _apply(conn, "mtgo", before, None) == before
    assert _stored(conn) == row


# mtgo.com: a refusal


@pytest.mark.parametrize("status", [401, 403, 451])
def test_mtgo_refusal_from_none_pauses_now(conn, status):
    after = _apply(conn, "mtgo", None, _refused(status))
    assert _stored(conn) == {
        "status": "paused", "http_status": status, "answers": 0, "since": NOW_S,
        "last_status": status, "last_at": NOW_S, "not_before": None,
    }
    assert after == read_hold(conn, "mtgo")


@pytest.mark.parametrize(
    ("cause", "answers"), [(429, 0), (503, 2)],
)
def test_mtgo_refusal_ends_a_wait_and_the_pause_begins_then(conn, cause, answers):
    # k4: a wait that ends in a refusal begins the pause at the refusal.
    before = _seed(conn, "mtgo", "waiting", cause, answers=answers,
                   since="2026-10-05T09:00:00Z", not_before="2026-10-05T12:00:00Z")
    _apply(conn, "mtgo", before, _refused(401))
    assert _stored(conn) == {
        "status": "paused", "http_status": 401, "answers": 0, "since": NOW_S,
        "last_status": 401, "last_at": NOW_S, "not_before": None,
    }


def test_mtgo_refusal_while_paused_replaces_the_cause_and_keeps_the_date(conn):
    before = _seed(conn, "mtgo", "paused", 429, since="2026-10-03T08:00:00Z",
                   not_before="2026-10-05T11:00:00Z")
    _apply(conn, "mtgo", before, _refused(403))
    assert _stored(conn) == {
        "status": "paused", "http_status": 403, "answers": 0,
        "since": "2026-10-03T08:00:00Z", "last_status": 403, "last_at": NOW_S,
        "not_before": None,
    }


# mtgo.com: a 429


@pytest.mark.parametrize(
    ("ra", "not_before"),
    [
        # now + 3 h is 15:00:30, rounded up to 15:01
        (None, "2026-10-05T15:01:00Z"),
        # a Retry-After shorter than three hours does not shorten the wait
        (_t("2026-10-05T13:00:00Z"), "2026-10-05T15:01:00Z"),
        # a longer one is kept, rounded up to the minute
        (_t("2026-10-05T16:20:10Z"), "2026-10-05T16:21:00Z"),
    ],
)
def test_mtgo_first_429_waits_at_least_three_hours(conn, ra, not_before):
    _apply(conn, "mtgo", None, _rate(ra=ra))
    assert _stored(conn) == {
        "status": "waiting", "http_status": 429, "answers": 0, "since": NOW_S,
        "last_status": 429, "last_at": NOW_S, "not_before": not_before,
    }


def test_mtgo_429_during_a_503_wait_starts_a_429_wait(conn):
    before = _seed(conn, "mtgo", "waiting", 503, answers=2, since="2026-10-05T09:00:00Z",
                   not_before="2026-10-05T12:00:00Z")
    _apply(conn, "mtgo", before, _rate())
    assert _stored(conn) == {
        "status": "waiting", "http_status": 429, "answers": 0, "since": NOW_S,
        "last_status": 429, "last_at": NOW_S, "not_before": "2026-10-05T15:01:00Z",
    }


@pytest.mark.parametrize(
    ("ra", "first", "not_before"),
    [
        # no Retry-After: now + 1 h, 13:00:30, rounded up
        (None, True, "2026-10-05T13:01:00Z"),
        (_t("2026-10-05T17:45:00Z"), True, "2026-10-05T17:45:00Z"),
        (_t("2026-10-05T17:45:01Z"), True, "2026-10-05T17:46:00Z"),
        # a 429 at a later page after a 429 wait is still the second in a row
        (None, False, "2026-10-05T13:01:00Z"),
    ],
)
def test_mtgo_second_429_in_a_row_pauses(conn, ra, first, not_before):
    before = _seed(conn, "mtgo", "waiting", 429, since="2026-10-05T09:00:00Z",
                   not_before="2026-10-05T12:00:00Z")
    _apply(conn, "mtgo", before, _rate(ra=ra, first=first), page_read=not first)
    assert _stored(conn) == {
        "status": "paused", "http_status": 429, "answers": 0, "since": NOW_S,
        "last_status": 429, "last_at": NOW_S, "not_before": not_before,
    }


def test_a_timeout_between_two_429s_leaves_the_streak_alone(conn):
    before = _seed(conn, "mtgo", "waiting", 429, since="2026-10-05T09:00:00Z",
                   not_before="2026-10-05T12:00:00Z")
    timeout = Answer(kind=AnswerKind.GENERIC, reason="timed out", at=NOW, place="index",
                     first_request=True)
    assert _apply(conn, "mtgo", before, timeout) == before
    _apply(conn, "mtgo", read_hold(conn, "mtgo"), _rate())
    assert _stored(conn)["status"] == "paused"


@pytest.mark.parametrize(
    ("ra", "not_before"),
    [
        (None, "2026-10-05T13:01:00Z"),
        (_t("2026-10-05T18:00:05Z"), "2026-10-05T18:01:00Z"),
    ],
)
def test_mtgo_429_while_paused_keeps_cause_and_date_and_sets_the_not_before(
    conn, ra, not_before
):
    before = _seed(conn, "mtgo", "paused", 503, answers=3, since="2026-10-03T08:00:00Z")
    _apply(conn, "mtgo", before, _rate(ra=ra))
    assert _stored(conn) == {
        "status": "paused", "http_status": 503, "answers": 3,
        "since": "2026-10-03T08:00:00Z", "last_status": 429, "last_at": NOW_S,
        "not_before": not_before,
    }


# mtgo.com: a 503


@pytest.mark.parametrize(
    ("first", "page_read", "ra", "answers", "not_before"),
    [
        # now + 1 h is 13:00:30, rounded up to 13:01
        (True, False, None, 1, "2026-10-05T13:01:00Z"),
        (False, True, None, 0, "2026-10-05T13:01:00Z"),
        # a shorter Retry-After does not shorten the hour; a longer one wins
        (True, False, _t("2026-10-05T12:30:00Z"), 1, "2026-10-05T13:01:00Z"),
        (True, False, _t("2026-10-05T14:10:05Z"), 1, "2026-10-05T14:11:00Z"),
    ],
)
def test_mtgo_503_from_none_waits_an_hour(conn, first, page_read, ra, answers, not_before):
    _apply(conn, "mtgo", None, _unavailable(ra=ra, first=first), page_read=page_read)
    assert _stored(conn) == {
        "status": "waiting", "http_status": 503, "answers": answers, "since": NOW_S,
        "last_status": 503, "last_at": NOW_S, "not_before": not_before,
    }


def test_mtgo_503_during_a_429_wait_starts_a_503_wait(conn):
    before = _seed(conn, "mtgo", "waiting", 429, since="2026-10-05T09:00:00Z",
                   not_before="2026-10-05T12:00:00Z")
    _apply(conn, "mtgo", before, _unavailable())
    assert _stored(conn) == {
        "status": "waiting", "http_status": 503, "answers": 1, "since": NOW_S,
        "last_status": 503, "last_at": NOW_S, "not_before": "2026-10-05T13:01:00Z",
    }


@pytest.mark.parametrize(
    ("answers", "since", "first", "page_read", "expected_answers", "expected_since"),
    [
        # a first-request 503 adds one, and the date stays
        (1, "2026-10-05T10:00:00Z", True, False, 2, "2026-10-05T10:00:00Z"),
        # counting from 0 starts the date now
        (0, "2026-10-05T10:00:00Z", True, False, 1, NOW_S),
        # k1: a page read before the 503 restarts the count; the date stays
        (2, "2026-10-05T10:00:00Z", False, True, 0, "2026-10-05T10:00:00Z"),
        # ...even when the 24 h have long passed
        (10, "2026-10-03T10:00:00Z", False, True, 0, "2026-10-03T10:00:00Z"),
        # 24 h one second short: three or more, but not yet a day
        (5, "2026-10-04T12:00:31Z", True, False, 6, "2026-10-04T12:00:31Z"),
        # more than a day, but the third answer has not come
        (1, "2026-10-03T12:00:00Z", True, False, 2, "2026-10-03T12:00:00Z"),
    ],
)
def test_mtgo_503_during_a_503_wait_counts_first_request_answers(
    conn, answers, since, first, page_read, expected_answers, expected_since
):
    before = _seed(conn, "mtgo", "waiting", 503, answers=answers, since=since,
                   not_before="2026-10-05T12:00:00Z")
    _apply(conn, "mtgo", before, _unavailable(first=first), page_read=page_read)
    assert _stored(conn) == {
        "status": "waiting", "http_status": 503, "answers": expected_answers,
        "since": expected_since, "last_status": 503, "last_at": NOW_S,
        "not_before": "2026-10-05T13:01:00Z",
    }


@pytest.mark.parametrize(
    ("ra", "not_before"),
    [
        (None, None),
        (_t("2026-10-05T17:59:59Z"), "2026-10-05T18:00:00Z"),
    ],
)
def test_mtgo_a_day_of_first_request_503s_pauses(conn, ra, not_before):
    # The third first-request 503, exactly 24 h after the first.
    before = _seed(conn, "mtgo", "waiting", 503, answers=2, since="2026-10-04T12:00:30Z",
                   not_before="2026-10-05T12:00:00Z")
    _apply(conn, "mtgo", before, _unavailable(ra=ra))
    assert _stored(conn) == {
        "status": "paused", "http_status": 503, "answers": 3, "since": NOW_S,
        "last_status": 503, "last_at": NOW_S, "not_before": not_before,
    }


@pytest.mark.parametrize("cause", [403, 503])
@pytest.mark.parametrize(
    ("ra", "not_before"),
    [
        (None, None),
        (_t("2026-10-05T19:00:00Z"), "2026-10-05T19:00:00Z"),
    ],
)
def test_mtgo_503_while_paused_keeps_cause_and_date(conn, cause, ra, not_before):
    # k3: the not-before comes from Retry-After when it carries one, else none.
    before = _seed(conn, "mtgo", "paused", cause, answers=3 if cause == 503 else 0,
                   since="2026-10-03T08:00:00Z", not_before="2026-10-05T11:00:00Z")
    _apply(conn, "mtgo", before, _unavailable(ra=ra))
    assert _stored(conn) == {
        "status": "paused", "http_status": cause, "answers": 3 if cause == 503 else 0,
        "since": "2026-10-03T08:00:00Z", "last_status": 503, "last_at": NOW_S,
        "not_before": not_before,
    }


# A generic answer, for either source


@pytest.mark.parametrize(
    ("source", "seed"),
    [
        ("mtgo", None),
        ("mtgo", ("waiting", 429, 0, "2026-10-05T13:00:00Z")),
        ("mtgo", ("waiting", 503, 2, "2026-10-05T12:30:00Z")),
        ("mtgo", ("paused", 403, 0, None)),
        # TopDeck: every format unanswered. It has no 503 hold to keep.
        ("topdeck", None),
        ("topdeck", ("waiting", 429, 0, "2026-10-05T13:00:00Z")),
        ("topdeck", ("paused", 403, 0, None)),
    ],
)
def test_a_generic_answer_leaves_the_row_unchanged(conn, source, seed):
    before = None
    if seed is not None:
        status, cause, answers, nb = seed
        before = _seed(conn, source, status, cause, answers=answers, not_before=nb,
                       last_status=cause, last_at="2026-10-05T10:00:00Z")
    row = _stored(conn, source)
    generic = Answer(kind=AnswerKind.GENERIC, reason="HTTP 500 Internal Server Error",
                     at=NOW, http_status=500, place="index", first_request=True)
    assert _apply(conn, source, before, generic) == before
    assert _stored(conn, source) == row


# TopDeck


@pytest.mark.parametrize(
    ("ra_s", "ra", "not_before"),
    [
        # retryAfterSeconds, to the second, with no floor (D18)
        (42, None, "2026-10-05T12:01:12Z"),
        (5, None, "2026-10-05T12:00:35Z"),
        # a fraction of a second is rounded up, never down
        (41.2, None, "2026-10-05T12:01:12Z"),
        # the body comes before the header
        (42, _t("2026-10-05T14:00:00Z"), "2026-10-05T12:01:12Z"),
        # the header alone, not rounded to the minute
        (None, _t("2026-10-05T12:20:05Z"), "2026-10-05T12:20:05Z"),
        # neither: now + 1 h
        (None, None, "2026-10-05T13:00:30Z"),
    ],
)
def test_topdeck_first_429_waits_topdecks_own_time(conn, ra_s, ra, not_before):
    answer = _answer(AnswerKind.RATE, 429, ra=ra, ra_s=ra_s)
    _apply(conn, "topdeck", None, answer)
    assert _stored(conn, "topdeck") == {
        "status": "waiting", "http_status": 429, "answers": 0, "since": NOW_S,
        "last_status": 429, "last_at": NOW_S, "not_before": not_before,
    }


def test_topdeck_second_429_in_a_row_pauses(conn):
    before = _seed(conn, "topdeck", "waiting", 429, since="2026-10-05T11:00:00Z",
                   not_before="2026-10-05T12:00:00Z")
    _apply(conn, "topdeck", before, _rate(ra_s=600))
    assert _stored(conn, "topdeck") == {
        "status": "paused", "http_status": 429, "answers": 0, "since": NOW_S,
        "last_status": 429, "last_at": NOW_S, "not_before": "2026-10-05T12:10:30Z",
    }


def test_topdeck_429_while_paused_keeps_cause_and_date(conn):
    before = _seed(conn, "topdeck", "paused", 401, since="2026-10-03T08:00:00Z")
    _apply(conn, "topdeck", before, _rate())
    assert _stored(conn, "topdeck") == {
        "status": "paused", "http_status": 401, "answers": 0,
        "since": "2026-10-03T08:00:00Z", "last_status": 429, "last_at": NOW_S,
        "not_before": "2026-10-05T13:00:30Z",
    }


@pytest.mark.parametrize(
    ("seed", "status", "since"),
    [
        (None, 403, NOW_S),
        (("waiting", 429, "2026-10-05T11:00:00Z"), 401, NOW_S),
        (("paused", 429, "2026-10-03T08:00:00Z"), 403, "2026-10-03T08:00:00Z"),
    ],
)
def test_topdeck_refusal_works_as_for_mtgo(conn, seed, status, since):
    before = None
    if seed is not None:
        before = _seed(conn, "topdeck", seed[0], seed[1], since=seed[2],
                       not_before="2026-10-05T11:30:00Z")
    _apply(conn, "topdeck", before, _refused(status))
    assert _stored(conn, "topdeck") == {
        "status": "paused", "http_status": status, "answers": 0, "since": since,
        "last_status": status, "last_at": NOW_S, "not_before": None,
    }


@pytest.mark.parametrize(
    "seed", [("waiting", 429, "2026-10-05T11:00:00Z"), ("paused", 403, None)]
)
def test_topdeck_a_completed_run_lifts_any_hold(conn, seed):
    # k6: a run no 429 or refusal ended, with one format answered.
    before = _seed(conn, "topdeck", seed[0], seed[1], not_before=seed[2])
    assert _apply(conn, "topdeck", before, None, completed=True) is None
    assert _stored(conn, "topdeck") is None


def test_topdeck_takes_no_503_hold(conn):
    with pytest.raises(ValueError):
        _apply(conn, "topdeck", None, _unavailable())
    assert _stored(conn, "topdeck") is None


# The holds are per source


def test_one_sources_outcome_leaves_the_others_hold_alone(conn):
    td = _seed(conn, "topdeck", "paused", 403, since="2026-10-03T08:00:00Z")
    _apply(conn, "mtgo", None, _rate())
    assert read_hold(conn, "topdeck") == td
    _apply(conn, "mtgo", read_hold(conn, "mtgo"), None, completed=True)
    assert read_hold(conn, "topdeck") == td


def test_the_hold_returned_is_the_hold_stored(conn):
    now = NOW + timedelta(microseconds=700_000)
    after = _apply(conn, "mtgo", None, _rate(at=now), now=now)
    assert after == read_hold(conn, "mtgo")
    assert after == Hold(
        source="mtgo", status=HoldStatus.WAITING, http_status=429, answers=0,
        since=NOW, last_status=429, last_at=NOW, not_before=_t("2026-10-05T15:01:00Z"),
    )


def test_contradictory_outcomes_are_refused(conn):
    with pytest.raises(ValueError):
        _apply(conn, "mtgo", None, _rate(), completed=True)
    with pytest.raises(ValueError):
        _apply(conn, "fbettega", None, _rate())
    assert _stored(conn) is None


# Answer and RefreshResult


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (401, AnswerKind.REFUSED), (403, AnswerKind.REFUSED), (451, AnswerKind.REFUSED),
        (429, AnswerKind.RATE), (503, AnswerKind.UNAVAILABLE),
        (500, AnswerKind.GENERIC), (404, AnswerKind.GENERIC), (None, AnswerKind.GENERIC),
    ],
)
def test_answer_kind(status, kind):
    assert answer_kind(status) == kind


def test_answer_needs_a_status_unless_generic():
    with pytest.raises(ValueError):
        Answer(kind=AnswerKind.RATE, reason="", at=NOW)
    with pytest.raises(ValueError):
        Answer(kind="slow", reason="", at=NOW, http_status=429)
    assert Answer(kind=AnswerKind.GENERIC, reason="timed out", at=NOW).http_status is None


def test_answer_reason_follows_the_line_catalog():
    url = "https://example.invalid/decklists"
    assert answer_reason(
        urllib.error.HTTPError(url, 503, "Service Unavailable", None, None)
    ) == "HTTP 503 Service Unavailable"
    assert answer_reason(
        urllib.error.HTTPError(url, 429, "", None, None)
    ) == "HTTP 429 Too Many Requests"
    assert answer_reason(TimeoutError("The read operation timed out")) == "timed out"
    assert answer_reason(urllib.error.URLError(TimeoutError("connect"))) == "timed out"
    refused = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
    assert answer_reason(refused) == str(refused)


def test_refresh_result_new_fields_default_for_todays_callers():
    result = RefreshResult(status="failed", error="x")
    assert (result.hold_before, result.hold_after, result.answer, result.by_hand) == (
        None, None, None, False
    )
    assert (result.answered, result.unfetched, result.unanswered) == ((), (), ())
