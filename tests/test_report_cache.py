"""Unit-level tests for the tokens and cache api/sql.py's shared report
cache is built from: ``_corpus_token``, ``_report_inputs_token`` and
``_shared_report_cache`` itself, plus the corpus token's effect on
``_cached_consensus``.

These stay below the HTTP layer (a raw ``sqlite3`` connection, no
``TestClient``) the same way ``test_intermission.py`` tests
``_cached_break_read`` directly, with the same ``_FakeRequest``/``_FakeApp``
stand-in for FastAPI's own ``Request`` -- cheaper than a full app for a
check that only needs ``request.app.state`` to exist, and it lets these
tests reach ``_cached_consensus`` without standing up a live match. The
HTTP-level behaviour (a real ``/api/review/leaks`` call reusing or rebuilding
a report, and the cross-route share with ``/api/guide/{key}``) is pinned in
``tests/test_api.py`` instead, against the real fixture database.
"""

from __future__ import annotations

import pytest

import sensei_top.api.sql as sql_mod
from sensei_top.api.sql import (
    _cached_consensus,
    _corpus_token,
    _report_inputs_token,
    _shared_report_cache,
)
from sensei_top.db import open_database
from sensei_top.review.consensus import ArchetypeConsensus


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


class _FakeAppState:
    """Just enough of ``app.state`` for the caches under test -- mirrors
    ``api/app.py::create_app``'s own pre-registration of these three dicts
    (unlike ``break_cache``/``break_classify_caches``, which stay lazily
    created and so aren't needed here)."""

    def __init__(self):
        self.report_cache = None
        self.consensus_cache: dict = {}
        self.consensus_window_cache: dict = {}


class _FakeApp:
    def __init__(self):
        self.state = _FakeAppState()


class _FakeRequest:
    def __init__(self):
        self.app = _FakeApp()


def _insert_match(conn, match_id, result="win", deck_id=None, started_at="t"):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', ?, 't', ?, 1, 0, 'r')",
        (match_id, deck_id, started_at, result),
    )
    conn.execute(
        "INSERT INTO games (match_id, game_number, on_play, result, result_reason, "
        "turn_count, self_mulligans, opp_mulligans) VALUES (?, 1, 1, ?, NULL, 6, 0, 0)",
        (match_id, result),
    )


def _insert_meta_deck_archetype(
    conn, event_id="ev1", deck_ord=0, classified_at="2026-01-01T00:00:00Z"
):
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier, standings_rows) VALUES (?, 'p', 'sha', 'src', 'n', '2026-01-01', "
        "'Standard', 'A', 8)",
        (event_id,),
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "colors, label, method, classified_at) VALUES (?, ?, 'boros', 'Boros Aggro', 'RW', "
        "'Boros Aggro', 'archetype', ?)",
        (event_id, deck_ord, classified_at),
    )


# --- _corpus_token -----------------------------------------------------------


def test_corpus_token_moves_when_meta_deck_archetype_classified_at_changes(conn):
    """The classification stamp is what a dedup pass restamps unconditionally
    (see _corpus_token's own docstring) -- it must move the token even when
    no row was added or removed."""
    _insert_meta_deck_archetype(conn, classified_at="2026-01-01T00:00:00Z")
    conn.commit()

    before = _corpus_token(conn)
    conn.execute(
        "UPDATE meta_deck_archetype SET classified_at = '2026-02-02T00:00:00Z' "
        "WHERE event_id = 'ev1' AND deck_ord = 0"
    )
    conn.commit()
    after = _corpus_token(conn)

    assert before != after


def test_corpus_token_is_stable_across_two_calls_with_nothing_changed(conn):
    _insert_meta_deck_archetype(conn)
    conn.commit()
    assert _corpus_token(conn) == _corpus_token(conn)


# --- _report_inputs_token -----------------------------------------------------


def test_report_inputs_token_ignores_opponent_archetype_classified_at(conn):
    """classify_matches restamps classified_at on every rebuild, including
    ones that change no verdict, and the watcher rebuilds every few seconds
    while Arena is open -- keying the report cache on it would empty the
    cache that often for no reason."""
    _insert_match(conn, "m1")
    conn.execute(
        "INSERT INTO opponent_archetype (match_id, format, archetype_key, archetype_name, "
        "colors, label, method, confidence, cards_seen, conditions_met, conditions_unknown, "
        "evidence_json, classified_at) VALUES ('m1', 'Standard', 'boros', 'Boros Aggro', 'RW', "
        "'Boros Aggro', 'archetype', 'high', 5, 3, 0, NULL, '2026-01-01T00:00:00Z')"
    )
    conn.commit()

    before = _report_inputs_token(conn)
    conn.execute(
        "UPDATE opponent_archetype SET classified_at = '2026-02-02T00:00:00Z' WHERE match_id = 'm1'"
    )
    conn.commit()
    after = _report_inputs_token(conn)

    assert before == after


def test_report_inputs_token_moves_when_opponent_archetype_verdict_changes(conn):
    """A digested column (unlike classified_at above) must move the token --
    otherwise the exclusion above would be indistinguishable from digesting
    nothing at all."""
    _insert_match(conn, "m1")
    conn.execute(
        "INSERT INTO opponent_archetype (match_id, format, archetype_key, archetype_name, "
        "colors, label, method, confidence, cards_seen, conditions_met, conditions_unknown, "
        "evidence_json, classified_at) VALUES ('m1', 'Standard', 'boros', 'Boros Aggro', 'RW', "
        "'Boros Aggro', 'archetype', 'high', 5, 3, 0, NULL, '2026-01-01T00:00:00Z')"
    )
    conn.commit()

    before = _report_inputs_token(conn)
    conn.execute("UPDATE opponent_archetype SET confidence = 'low' WHERE match_id = 'm1'")
    conn.commit()
    after = _report_inputs_token(conn)

    assert before != after


def test_report_inputs_token_moves_when_a_match_result_changes(conn):
    _insert_match(conn, "m1", result="win")
    conn.commit()

    before = _report_inputs_token(conn)
    conn.execute("UPDATE matches SET result = 'loss' WHERE match_id = 'm1'")
    conn.commit()
    after = _report_inputs_token(conn)

    assert before != after


def test_report_inputs_token_moves_when_opponent_deck_override_is_written(conn):
    _insert_match(conn, "m1")
    conn.commit()

    before = _report_inputs_token(conn)
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label) VALUES ('m1', 'Rogue')"
    )
    conn.commit()
    after = _report_inputs_token(conn)

    assert before != after


def test_report_inputs_token_moves_when_only_an_override_archetype_key_changes(conn):
    """Every column is digested, not a hand-kept list: a re-pick that keeps
    the label and timestamp but changes only ``archetype_key`` (migration
    006's column) still moves the token."""
    _insert_match(conn, "m1")
    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label, updated_at, archetype_key) "
        "VALUES ('m1', 'Rogue', '2026-09-01T00:00:00', 'KeyA')"
    )
    conn.commit()

    before = _report_inputs_token(conn)
    conn.execute("UPDATE opponent_deck_override SET archetype_key = 'KeyB' WHERE match_id = 'm1'")
    conn.commit()
    after = _report_inputs_token(conn)

    assert before != after


def test_report_inputs_token_carries_the_corpus_token(conn):
    """A dedup/reclassification pass moves the corpus, not any of the
    match-scoped tables above -- the report cache still needs to see it,
    since a rebuilt MatchReport's opponent-consensus baseline comes from the
    same corpus (review/consensus.py::build_consensus)."""
    _insert_meta_deck_archetype(conn, classified_at="2026-01-01T00:00:00Z")
    conn.commit()

    before = _report_inputs_token(conn)
    conn.execute(
        "UPDATE meta_deck_archetype SET classified_at = '2026-02-02T00:00:00Z' "
        "WHERE event_id = 'ev1' AND deck_ord = 0"
    )
    conn.commit()
    after = _report_inputs_token(conn)

    assert before != after


# --- _shared_report_cache -----------------------------------------------------


def test_shared_report_cache_returns_the_same_dict_across_calls_with_no_change(conn):
    request = _FakeRequest()
    first = _shared_report_cache(request, conn)
    second = _shared_report_cache(request, conn)
    assert first is second


def test_shared_report_cache_replaces_rather_than_clears_the_dict_on_a_token_change(conn):
    """FastAPI runs handlers in a threadpool: a concurrent request may still
    hold a reference to the old dict between its own ``in`` check and its
    read. Replacing app.state.report_cache's tuple, rather than calling
    .clear() on the dict in place, must leave any reference already holding
    the old dict fully intact -- checked here by keeping our own reference
    and reading it back after the token has moved."""
    _insert_match(conn, "m1")
    conn.commit()

    request = _FakeRequest()
    old_cache = _shared_report_cache(request, conn)
    old_cache[("m1", None)] = "sentinel-report"

    # Move the token without touching report_cache's own inner dict at all.
    _insert_match(conn, "m2")
    conn.commit()

    new_cache = _shared_report_cache(request, conn)

    assert new_cache is not old_cache
    assert old_cache[("m1", None)] == "sentinel-report"  # untouched by the replace
    assert ("m1", None) not in new_cache  # the new dict starts empty


# --- _cached_consensus, pinned to the corpus token ----------------------------


def test_cached_consensus_rebuilds_when_the_corpus_token_moves(conn, monkeypatch):
    """_cached_consensus's cache key carries _corpus_token -- a
    sensei-top meta reclassification (which always restamps
    meta_deck_archetype.classified_at, per _corpus_token's own docstring)
    must not hand back a consensus built from the superseded corpus."""
    _insert_meta_deck_archetype(conn, classified_at="2026-01-01T00:00:00Z")
    conn.commit()

    calls = []

    def fake_build_consensus(conn, archetype_key, *, board="main", since=None):
        calls.append(archetype_key)
        return ArchetypeConsensus(archetype_key=archetype_key, deck_count=0, cards=())

    monkeypatch.setattr(sql_mod, "build_consensus", fake_build_consensus)

    request = _FakeRequest()
    first = _cached_consensus(request, conn, "archetype:boros")
    assert calls == ["boros"]

    second = _cached_consensus(request, conn, "archetype:boros")
    assert calls == ["boros"]  # reused, no second build
    assert second is first

    conn.execute(
        "UPDATE meta_deck_archetype SET classified_at = '2026-02-02T00:00:00Z' "
        "WHERE event_id = 'ev1' AND deck_ord = 0"
    )
    conn.commit()

    third = _cached_consensus(request, conn, "archetype:boros")
    assert calls == ["boros", "boros"]  # the token moved; rebuilt
    assert third is not second
