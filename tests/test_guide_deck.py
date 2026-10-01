"""Tests for guide/deck.py: stitching a player's deck identity across list
edits, using the ``deck_guids`` table the projector already writes but that
nothing previously read back.
"""

from __future__ import annotations

import json

import pytest

from sensei_top.db import open_database
from sensei_top.guide.deck import list_identities, resolve


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "t.db")
    yield c
    c.close()


def _insert_deck(conn, deck_id, *, name=None, fmt="TraditionalStandard", cards=None):
    conn.execute(
        "INSERT INTO decks (deck_id, name, format, cards_json, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, 't', 't')",
        (deck_id, name, fmt, json.dumps(cards or {"maindeck": [], "sideboard": []})),
    )


def _insert_guid(conn, deck_id, arena_deck_id, last_seen="t"):
    conn.execute(
        "INSERT INTO deck_guids (deck_id, arena_deck_id, version, format, last_seen) "
        "VALUES (?, ?, '1', 'TraditionalStandard', ?)",
        (deck_id, arena_deck_id, last_seen),
    )


def _insert_match(conn, match_id, deck_id, result, started_at, *, games_won=2, games_lost=0):
    conn.execute(
        "INSERT INTO matches (match_id, event_id, deck_id, self_seat, opponent_seat, "
        "opponent_user_id, opponent_name, started_at, ended_at, result, games_won, "
        "games_lost, completed_reason) VALUES (?, 'e', ?, 1, 2, 'u', 'n', ?, ?, ?, ?, ?, 'r')",
        (match_id, deck_id, started_at, started_at, result, games_won, games_lost),
    )


def test_two_deck_ids_sharing_one_arena_guid_resolve_to_one_identity(conn):
    """A single sideboard-card swap mints a new content-hash deck_id, but
    it's still the same Arena deck (deck_guids.arena_deck_id) — the guide
    must see one deck with combined match history, not two fragments."""
    _insert_deck(conn, "hash1", name="Spellelementals")
    _insert_deck(conn, "hash2", name="Spellelementals")
    _insert_guid(conn, "hash1", "guid-abc")
    _insert_guid(conn, "hash2", "guid-abc")
    _insert_match(conn, "m1", "hash1", "win", "2026-08-13T00:00:00")
    _insert_match(conn, "m2", "hash2", "loss", "2026-08-14T00:00:00")
    conn.commit()

    identities = list_identities(conn)
    assert len(identities) == 1
    identity = identities[0]
    assert identity.key == "guid:guid-abc"
    assert identity.arena_deck_id == "guid-abc"
    assert set(identity.deck_ids) == {"hash1", "hash2"}
    assert identity.matches == 2
    assert identity.match_wins == 1
    assert identity.match_losses == 1


def test_a_deck_id_under_two_guids_lands_in_only_the_more_recent_one(conn):
    """Regression test for a real double count: deck_guids can register the
    same content hash under two different Arena decks (the same list
    re-registered). The hash must resolve to exactly one identity — the
    Arena deck that used it most recently — never be summed into both."""
    _insert_deck(conn, "shared_hash", name="Spellelementals")
    _insert_guid(conn, "shared_hash", "guid-early", last_seen="2026-08-31")
    _insert_guid(conn, "shared_hash", "guid-late", last_seen="2026-09-01")
    _insert_match(conn, "m1", "shared_hash", "win", "2026-08-13T00:00:00")
    _insert_match(conn, "m2", "shared_hash", "loss", "2026-08-14T00:00:00")
    conn.commit()

    identities = list_identities(conn)
    assert len(identities) == 1
    assert identities[0].key == "guid:guid-late"
    assert sum(i.matches for i in identities) == 2


def test_a_deck_with_no_guid_row_still_resolves(conn):
    """A truncated log can produce a match whose deck_id was never paired
    with an arena_deck_id — it must not vanish from the guide picker."""
    _insert_deck(conn, "orphan_hash", name="Mystery Deck")
    _insert_match(conn, "m1", "orphan_hash", "win", "2026-08-13T00:00:00")
    conn.commit()

    identities = list_identities(conn)
    assert len(identities) == 1
    assert identities[0].key == "deck:orphan_hash"
    assert identities[0].arena_deck_id is None
    assert identities[0].deck_ids == ("orphan_hash",)


def test_current_cards_comes_from_the_most_recently_played_version(conn):
    """decks.last_seen is unreliable (the projector's own ON CONFLICT branch
    is unreachable) — the guide must derive "current" from matches.started_at
    instead."""
    old_cards = {"maindeck": [1, 1, 1, 1], "sideboard": []}
    new_cards = {"maindeck": [2, 2, 2, 2], "sideboard": []}
    _insert_deck(conn, "hash_old", name="Deck", cards=old_cards)
    _insert_deck(conn, "hash_new", name="Deck", cards=new_cards)
    _insert_guid(conn, "hash_old", "guid-x")
    _insert_guid(conn, "hash_new", "guid-x")
    _insert_match(conn, "m1", "hash_old", "win", "2026-08-13T00:00:00")
    _insert_match(conn, "m2", "hash_new", "win", "2026-08-20T00:00:00")
    conn.commit()

    identity = list_identities(conn)[0]
    assert identity.current_cards == new_cards


def test_a_deck_never_played_is_excluded(conn):
    """decks/deck_guids can carry rows for a deck that was built but never
    taken into a match — the guide picker only lists decks with a record."""
    _insert_deck(conn, "hash1", name="Unplayed")
    _insert_guid(conn, "hash1", "guid-unplayed")
    conn.commit()

    assert list_identities(conn) == []


def test_resolve_finds_by_key(conn):
    _insert_deck(conn, "hash1", name="Deck A")
    _insert_guid(conn, "hash1", "guid-a")
    _insert_match(conn, "m1", "hash1", "win", "2026-08-13T00:00:00")
    conn.commit()

    identity = resolve(conn, "guid:guid-a")
    assert identity is not None
    assert identity.name == "Deck A"
    assert resolve(conn, "guid:nonexistent") is None


def test_games_won_and_lost_sum_across_matches(conn):
    _insert_deck(conn, "hash1", name="Deck A")
    _insert_match(conn, "m1", "hash1", "win", "2026-08-13T00:00:00", games_won=2, games_lost=1)
    _insert_match(conn, "m2", "hash1", "loss", "2026-08-14T00:00:00", games_won=1, games_lost=2)
    conn.commit()

    identity = resolve(conn, "deck:hash1")
    assert identity.games_won == 3
    assert identity.games_lost == 3
