"""Tests for brief/store.py: the authored-brief cache, and the two things
that make a stored brief stale."""

from __future__ import annotations

import pytest

from sensei_top.brief.store import (
    Brief,
    PlayAround,
    Staple,
    is_stale,
    list_hash,
    read_brief,
    write_brief,
)
from sensei_top.db import open_database
from sensei_top.guide.narrative import BoardCard
from sensei_top.guide.plans import PlanProblem


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _brief(**overrides) -> Brief:
    defaults = dict(
        deck_key="guid:abc",
        archetype_key="mardu_discard",
        archetype_label="Mardu Discard",
        archetype_share=0.086,
        personal_matches=3,
        personal_wins=2,
        personal_losses=1,
        prose="Their deck races you.",
        play_around=(PlayAround(card="Erode", why="one-mana kill spell"),),
        board_in=(BoardCard(card="Slagstorm", n=2),),
        board_out=(BoardCard(card="Get Out", n=2),),
        staples=(Staple(name="Marauding Mako", copies=4.0, share=1.0),),
        problems=(),
        prompt="the whole prompt text",
        model="claude-sonnet-5",
        generated_at="2026-08-20T00:00:00.000Z",
        corpus_commit="deadbeef",
        list_hash="hash1",
        source="live",
    )
    defaults.update(overrides)
    return Brief(**defaults)


def test_list_hash_changes_when_maindeck_changes():
    a = {"maindeck": [1, 1, 1, 2], "sideboard": [3, 3]}
    b = {"maindeck": [1, 1, 1, 1], "sideboard": [3, 3]}
    assert list_hash(a) != list_hash(b)


def test_list_hash_changes_when_sideboard_changes():
    a = {"maindeck": [1, 1, 1, 2], "sideboard": [3, 3]}
    b = {"maindeck": [1, 1, 1, 2], "sideboard": [3, 4]}
    assert list_hash(a) != list_hash(b)


def test_list_hash_is_stable_for_the_same_lists():
    a = {"maindeck": [2, 1, 1, 1], "sideboard": [4, 3]}
    b = {"maindeck": [1, 1, 1, 2], "sideboard": [3, 4]}
    assert list_hash(a) == list_hash(b)  # order within a board doesn't matter


def test_round_trip_write_read_preserves_every_field(conn):
    brief = _brief()
    write_brief(conn, brief)
    conn.commit()

    back = read_brief(conn, "guid:abc", "mardu_discard")
    assert back == brief


def test_is_stale_when_the_75_changed_under_it(conn):
    """A brief written for a different 75 may name cards the deck no longer
    holds — reported so the reader can decide to rewrite, never acted on."""
    conn.execute(
        "INSERT INTO meta_fetch (id, commit_sha, fetched_at, window_days, events) "
        "VALUES (1, 'deadbeef', 't', 90, 1)"
    )
    write_brief(conn, _brief(list_hash="hash1"))
    conn.commit()
    brief = read_brief(conn, "guid:abc", "mardu_discard")
    assert is_stale(conn, brief, current_list_hash="hash2") is True
    assert is_stale(conn, brief, current_list_hash="hash1") is False


def test_is_stale_when_the_corpus_moved(conn):
    conn.execute(
        "INSERT INTO meta_fetch (id, commit_sha, fetched_at, window_days, events) "
        "VALUES (1, 'newer-sha', 't', 90, 1)"
    )
    write_brief(conn, _brief(list_hash="hash1", corpus_commit="older-sha"))
    conn.commit()
    brief = read_brief(conn, "guid:abc", "mardu_discard")
    assert is_stale(conn, brief, current_list_hash="hash1") is True


def test_not_stale_when_both_still_match(conn):
    conn.execute(
        "INSERT INTO meta_fetch (id, commit_sha, fetched_at, window_days, events) "
        "VALUES (1, 'same-sha', 't', 90, 1)"
    )
    write_brief(conn, _brief(list_hash="hash1", corpus_commit="same-sha"))
    conn.commit()
    brief = read_brief(conn, "guid:abc", "mardu_discard")
    assert is_stale(conn, brief, current_list_hash="hash1") is False


def test_problems_round_trip(conn):
    brief = _brief(problems=(PlanProblem(archetype="Mardu Discard", message="unbalanced"),))
    write_brief(conn, brief)
    conn.commit()
    back = read_brief(conn, "guid:abc", "mardu_discard")
    assert back.problems == (PlanProblem(archetype="Mardu Discard", message="unbalanced"),)
