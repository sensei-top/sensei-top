"""Database setup tests: pragmas, migration application, idempotency."""


import re
import sqlite3
from importlib.resources import files
from pathlib import Path

import pytest

from sensei_top import db
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.reader.mtgo import ingest_mtgo_dir


@pytest.fixture
def conn(tmp_path):
    c = db.open_database(tmp_path / "test.db")
    yield c
    c.close()


def test_wal_mode_enabled(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_foreign_keys_enabled(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_migration_applied_once(tmp_path):
    path = tmp_path / "test.db"
    c = db.open_database(path)
    v1 = db.applied_version(c)
    assert v1 >= 1
    c.close()
    # reopening must be a no-op, not a re-application error
    c = db.open_database(path)
    assert db.applied_version(c) == v1
    assert (
        c.execute("SELECT COUNT(*) FROM schema_version WHERE version = ?", (v1,)).fetchone()[0]
        == 1
    )
    c.close()


def test_expected_tables_and_views_exist(conn):
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")
    }
    for required in (
        "raw_events", "decks", "matches", "games", "turns",
        "v_deck_winrate", "v_play_draw_winrate", "v_deck_game_length", "v_deck_turn_curves",
        "v_deck_identity", "v_deck_identity_winrate",
        "backup_state",
    ):
        assert required in names, f"missing {required}"


def test_raw_events_digest_unique(conn):
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, payload) VALUES ('d1','f','event','{}')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO raw_events (digest, source_file, kind, payload)"
            " VALUES ('d1','f','event','{}')"
        )


def test_migrations_are_found_inside_the_package():
    """A wheel carries only what is inside the package, so discovery must look there."""
    found = db.discover_migrations()
    package = Path(str(files("sensei_top"))) / "migrations"
    assert found[0][0] == 1
    assert {Path(str(p)).parent for _, p in found} == {package}


def test_bad_migration_filename_rejected(tmp_path):
    bad = tmp_path / "migrations"
    bad.mkdir()
    (bad / "init.sql").write_text("SELECT 1;")
    with pytest.raises(ValueError):
        db.discover_migrations(bad)


def test_migration_006_wipes_pre_existing_free_text_overrides(tmp_path):
    """`opponent_deck_override` predates `archetype_key`. A free-text row from
    before the picker existed (the old "name it" feature) has no
    `archetype_key` and cannot be reconciled with the candidate list, so 006
    clears the table rather than leaving stale text behind."""
    path = tmp_path / "upgrade.db"
    conn = db.connect(path)
    for version, migration_path in db.discover_migrations():
        if version > 5:
            break
        sql = migration_path.read_text(encoding="utf-8")
        conn.execute("BEGIN")
        for statement in db._split_statements(sql):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.execute("COMMIT")
    assert db.applied_version(conn) == 5

    conn.execute(
        "INSERT INTO opponent_deck_override (match_id, label) VALUES ('m1', 'Old Free Text')"
    )

    applied = db.migrate(conn)

    assert 6 in applied
    assert conn.execute("SELECT COUNT(*) FROM opponent_deck_override").fetchone()[0] == 0
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(opponent_deck_override)")}
    assert "archetype_key" in cols
    conn.close()


def test_failed_migration_rolls_back(tmp_path):
    mdir = tmp_path / "migrations"
    mdir.mkdir()
    (mdir / "001_ok.sql").write_text("CREATE TABLE schema_version (version INTEGER PRIMARY KEY);")
    (mdir / "002_bad.sql").write_text("CREATE TABLE t1 (x); CREATE TABLE t1 (x);")
    c = db.connect(tmp_path / "t.db")
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(c, mdir)  # applies 001, then 002 fails and must roll back
    names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "t1" not in names  # 002 rolled back entirely
    assert db.applied_version(c) == 1  # 001 stayed applied
    c.close()


# --- 037_mtgo_logged_at_separator: repairing the ORIGINAL 036's bug -----------
#
# The first cut of 036_mtgo_live.sql normalized MTGO's stored logged_at with
# bare `datetime(logged_at, 'localtime')`, which returns a SPACE-separated
# string ('2026-09-14 12:42:44') rather than the 'T'-separated ISO shape every
# Arena timestamp uses. That inverted Bug A: ' ' (0x20) sorts below every
# digit while 'T' (0x54) sorts above every digit, so a space-form MTGO row
# sorted as strictly OLDER than any same-instant Arena row. 036 itself is now
# fixed (it produces 'T' form directly), so these tests build a database
# already stuck at schema_version 36 with rows in the old, broken shape —
# exactly what a real database that applied the original 036 looks like —
# and confirm 037 repairs them without re-shifting the clock.


def _migrate_to(conn: sqlite3.Connection, *, through_version: int) -> None:
    """Apply migrations up to and including ``through_version`` only — the
    same manual loop test_migration_006_wipes_pre_existing_free_text_overrides
    already uses to build a database frozen at a specific past schema."""
    for version, migration_path in db.discover_migrations():
        if version > through_version:
            break
        sql = migration_path.read_text(encoding="utf-8")
        conn.execute("BEGIN")
        for statement in db._split_statements(sql):
            conn.execute(statement)
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        conn.execute("COMMIT")


def test_migration_037_repairs_space_separated_mtgo_timestamps(tmp_path):
    conn = db.connect(tmp_path / "stuck_at_36.db")
    _migrate_to(conn, through_version=36)
    assert db.applied_version(conn) == 36

    # A raw_events row exactly as the ORIGINAL 036 would have left it: space,
    # not 'T'.
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source) "
        "VALUES ('broken', 'Match_GameLog_x.dat', '2026-09-14 12:42:44', 'event', "
        "'MtgoGameLog', 'cGF5bG9hZA==', 'mtgo')"
    )
    # A row that was already correct (this database's serve --watch had
    # already restarted and picked up a fixed reader/mtgo.py's _mtime_iso
    # before 037 exists) — must be left byte-for-byte alone.
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source) "
        "VALUES ('already_ok', 'Match_GameLog_y.dat', '2026-09-14T12:50:00', 'event', "
        "'MtgoGameLog', 'cGF5bG9hZA==', 'mtgo')"
    )
    # An Arena row that would never actually be space-form in practice, but
    # proves the WHERE source='mtgo' clause protects Arena rows regardless.
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source) "
        "VALUES ('arena_row', 'Player.log', '2026-09-14 09:00:00', 'event', "
        "'MatchGameRoomStateChangedEvent', '{}', 'arena')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, started_at, ended_at, result, source) "
        "VALUES ('mtgo-match', '2026-09-14 12:42:44', '2026-09-14 12:45:00', 'win', 'mtgo')"
    )
    conn.commit()

    applied = db.migrate(conn)
    assert 37 in applied

    rows = {
        r["digest"]: r["logged_at"]
        for r in conn.execute("SELECT digest, logged_at FROM raw_events")
    }
    assert rows["broken"] == "2026-09-14T12:42:44"  # reshaped, same instant
    assert rows["already_ok"] == "2026-09-14T12:50:00"  # untouched (no-op)
    assert rows["arena_row"] == "2026-09-14 09:00:00"  # never touched: not 'mtgo'

    match = conn.execute(
        "SELECT started_at, ended_at FROM matches WHERE match_id = 'mtgo-match'"
    ).fetchone()
    assert match["started_at"] == "2026-09-14T12:42:44"
    assert match["ended_at"] == "2026-09-14T12:45:00"
    conn.close()


def test_migration_037_is_a_true_no_op_on_a_fresh_database(tmp_path):
    """A brand-new database runs the FIXED 036 directly, so 037 must find
    nothing left to repair — proof the two migrations agree on the same
    end state rather than 037 masking a still-broken 036."""
    conn = db.open_database(tmp_path / "fresh.db")
    conn.execute(
        "INSERT INTO raw_events (digest, source_file, logged_at, kind, label, payload, source) "
        "VALUES ('d1', 'Match_GameLog_x.dat', '2026-09-14T12:42:44', 'event', "
        "'MtgoGameLog', 'cGF5bG9hZA==', 'mtgo')"
    )
    conn.commit()
    before = conn.execute("SELECT logged_at FROM raw_events WHERE digest = 'd1'").fetchone()[0]
    # Re-running migrate() on an already-current database must not touch it.
    assert db.migrate(conn) == []
    after = conn.execute("SELECT logged_at FROM raw_events WHERE digest = 'd1'").fetchone()[0]
    assert after == before == "2026-09-14T12:42:44"
    conn.close()


_ARENA_FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
_MTGO_FIXTURE = Path(__file__).parent / "fixtures" / "mtgo_match_session.log"
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def test_every_logged_at_and_started_at_is_the_same_shape_on_both_sources(tmp_path, monkeypatch):
    """The end-to-end pin for Bug A (and its 037 regression): every stored
    timestamp on both sources is local-naive-seconds with a 'T' separator —
    no space, no 'Z', no numeric offset — through the REAL reader paths
    (reader/ingest.py's segmenter for Arena, reader/mtgo.py's _mtime_iso for
    MTGO), not a hand-written fixture value that could hide a reshaping bug
    either reader might reintroduce."""
    monkeypatch.setenv("MTGO_HANDLE", "Player1")
    db_path = tmp_path / "both_sources.db"
    conn = db.open_database(db_path)

    ingest_file(conn, _ARENA_FIXTURE, locale_hint="mdy")

    mtgo_dir = tmp_path / "mtgo-share"
    mtgo_dir.mkdir()
    (mtgo_dir / "Match_GameLog_f2244feb-54e1-48ec-b3c5-711b20844adf.dat").write_bytes(
        _MTGO_FIXTURE.read_bytes()
    )
    ingest_mtgo_dir(conn, mtgo_dir)

    project(conn)
    conn.commit()

    logged_at_rows = [r[0] for r in conn.execute("SELECT logged_at FROM raw_events").fetchall()]
    assert logged_at_rows, "fixture ingest must have produced rows"
    assert any(v is not None for v in logged_at_rows)
    for value in logged_at_rows:
        if value is not None:
            assert _TIMESTAMP_RE.fullmatch(value), value

    match_timestamps = conn.execute(
        "SELECT started_at, ended_at, source FROM matches"
    ).fetchall()
    assert len(match_timestamps) >= 2  # the 2 Arena matches, plus the MTGO one
    assert {r["source"] for r in match_timestamps} == {"arena", "mtgo"}
    for row in match_timestamps:
        for value in (row["started_at"], row["ended_at"]):
            if value is not None:
                assert _TIMESTAMP_RE.fullmatch(value), (row["source"], value)
    conn.close()


def test_migration_039_applies_to_an_existing_database(tmp_path):
    """Same recipe as 037's tests, via docs/architecture.md's "Adding a
    migration": build a database frozen at the prior schema with real rows
    already in it, migrate forward, and confirm the new table exists empty
    and the pre-existing rows are untouched."""
    conn = db.connect(tmp_path / "stuck_at_38.db")
    _migrate_to(conn, through_version=38)
    assert db.applied_version(conn) == 38

    conn.execute(
        "INSERT INTO raw_events (digest, source_file, kind, payload) "
        "VALUES ('pre-existing', 'Player.log', 'event', '{}')"
    )
    conn.commit()

    applied = db.migrate(conn)
    assert 39 in applied
    # db.migrate has no upper bound, so this also picks up every migration
    # added since 039 (040_arena_only_current_match.sql included) — the
    # version this lands on tracks HEAD, not 039 specifically.
    assert db.applied_version(conn) == db.discover_migrations()[-1][0]

    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "backup_state" in names
    assert conn.execute("SELECT COUNT(*) FROM backup_state").fetchone()[0] == 0

    row = conn.execute(
        "SELECT source_file, kind, payload FROM raw_events WHERE digest = 'pre-existing'"
    ).fetchone()
    assert row["source_file"] == "Player.log"
    assert row["kind"] == "event"
    assert row["payload"] == "{}"
    conn.close()


def test_migration_041_uppercases_existing_set_codes(tmp_path):
    """Same recipe as 037/039's tests: freeze a database at the prior schema,
    insert a row exactly as cards.py's two import paths left it before this
    change — one lowercase (the old Scryfall writer), one already uppercase
    (the Arena writer, which happened to already be uppercase in practice) —
    migrate forward, and confirm both end up uppercase, with a NULL set_code
    left alone rather than turned into the string 'NONE'."""
    conn = db.connect(tmp_path / "stuck_at_40.db")
    _migrate_to(conn, through_version=40)
    assert db.applied_version(conn) == 40

    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (1, 'Lowercase Sibling', 'rare', 'tla', '[]')"
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (2, 'Already Upper', 'rare', 'WOE', '[]')"
    )
    conn.execute(
        "INSERT INTO cards (grp_id, name, rarity, set_code, colors) "
        "VALUES (3, 'No Set Code', 'rare', NULL, '[]')"
    )
    conn.commit()

    applied = db.migrate(conn)
    assert 41 in applied

    rows = {r["grp_id"]: r["set_code"] for r in conn.execute("SELECT grp_id, set_code FROM cards")}
    assert rows[1] == "TLA"
    assert rows[2] == "WOE"
    assert rows[3] is None
    conn.close()


DRAFT_OBJECTS = (
    "v_current_pack", "v_current_draft", "v_draft_pool", "v_latest_draft",
    "draft_pack_cards", "draft_picks", "draft_packs", "draft_events",
    "card_ratings", "card_ratings_fetch",
    "limited_pick_stats", "limited_color_stats", "limited_card_stats", "limited_stats_fetch",
)


def test_migration_048_drops_every_draft_object(tmp_path):
    """Freeze a database at 047, where every draft table and view exists,
    give every link of the foreign-key chain a row so the drop order has to
    respect it, migrate forward, and confirm none of them is left — while
    the card columns 031 added for the draft assistant stay."""
    conn = db.connect(tmp_path / "stuck_at_47.db")
    _migrate_to(conn, through_version=47)
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert set(DRAFT_OBJECTS) <= names

    conn.execute("INSERT INTO draft_events (draft_id, ordinal) VALUES ('d1', 1)")
    conn.execute(
        "INSERT INTO draft_packs (draft_id, pack_number, pick_number, card_count) "
        "VALUES ('d1', 1, 1, 14)"
    )
    conn.execute(
        "INSERT INTO draft_pack_cards (draft_id, pack_number, pick_number, idx, grp_id) "
        "VALUES ('d1', 1, 1, 0, 1)"
    )
    conn.execute(
        "INSERT INTO draft_picks (draft_id, pack_number, pick_number, grp_id) "
        "VALUES ('d1', 1, 1, 1)"
    )
    conn.commit()

    applied = db.migrate(conn)
    assert 48 in applied

    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert names.isdisjoint(DRAFT_OBJECTS)
    assert "idx_card_ratings_grp" not in names
    card_columns = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
    assert {"power", "toughness", "keywords"} <= card_columns
    conn.close()


# --- 050_views_follow_mtgo_pick: the deck views read v_match_deck ------------
#
# One deck of each source, and four matches: an Arena match on the Arena deck
# (with a stray pick row that v_match_deck must ignore), an MTGO match picked
# to the MTGO deck, an MTGO match with no pick, and an MTGO match whose pick
# confirms only the format. Every expected count below is read off these rows.

_ARENA_DECK = "arena-deck"
_MTGO_DECK = "mtgo-deck"


def _seed_pick_rows(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES (?, 'Arena Deck', '{}'), "
        "(?, 'MTGO Deck', '{}')",
        (_ARENA_DECK, _MTGO_DECK),
    )
    conn.execute(
        "INSERT INTO matches"
        " (match_id, deck_id, started_at, result, games_won, games_lost, source) "
        "VALUES ('arena-1', ?, '2026-09-30T10:00:00', 'loss', 1, 2, 'arena'), "
        "('mtgo-picked', NULL, '2026-09-30T11:00:00', 'win', 2, 1, 'mtgo'), "
        "('mtgo-unpicked', NULL, '2026-09-30T12:00:00', 'win', 2, 0, 'mtgo'), "
        "('mtgo-format-only', NULL, '2026-09-30T13:00:00', 'loss', 0, 2, 'mtgo')",
        (_ARENA_DECK,),
    )
    conn.execute(
        "INSERT INTO mtgo_match_pick (match_id, deck_id, format) "
        "VALUES ('mtgo-picked', ?, 'Modern'), ('mtgo-format-only', NULL, 'Pauper'), "
        "('arena-1', ?, 'Modern')",
        (_MTGO_DECK, _MTGO_DECK),
    )
    conn.commit()


def test_migration_050_counts_a_picked_mtgo_match_under_its_deck(tmp_path):
    """Built at 049 with the rows already in place, then migrated, so 050 is
    shown to apply to an existing database as well as a fresh one."""
    conn = db.connect(tmp_path / "stuck_at_49.db")
    _migrate_to(conn, through_version=49)
    _seed_pick_rows(conn)

    assert 50 in db.migrate(conn)

    winrate = {
        (r["deck_id"], r["source"]): (
            r["matches_completed"], r["matches_won"], r["games_won"], r["games_lost"]
        )
        for r in conn.execute("SELECT * FROM v_deck_winrate")
    }
    # The picked MTGO match under its deck; the Arena match under its own deck
    # despite the stray pick; the two MTGO matches without a deck under none.
    assert winrate == {
        (_ARENA_DECK, "arena"): (1, 0, 1, 2),
        (_MTGO_DECK, "mtgo"): (1, 1, 2, 1),
    }

    matchups = {
        (r["deck_id"], r["source"], r["format"]): (
            r["matches_completed"], r["matches_won"], r["games_won"], r["games_lost"]
        )
        for r in conn.execute("SELECT * FROM v_matchup_winrate")
    }
    # No card_events or overrides, so every opponent is 'unknown' and the
    # groups are the deck alone, split by format since 058: the pick's format
    # for the picked and the format-only MTGO matches (Modern, Pauper), none
    # for the unpicked one and for the Arena match (a pick never applies to
    # Arena, and its log named no format).
    assert matchups == {
        (_ARENA_DECK, "arena", None): (1, 0, 1, 2),
        (_MTGO_DECK, "mtgo", "Modern"): (1, 1, 2, 1),
        (None, "mtgo", "Pauper"): (1, 0, 0, 2),
        (None, "mtgo", None): (1, 1, 2, 0),
    }
    conn.close()


def test_migration_050_gives_a_picked_mtgo_deck_a_deck_key(conn):
    """An MTGO deck has no deck_guids row, so v_deck_identity keys it by its
    deck_id, and only once a match is picked to it."""
    _seed_pick_rows(conn)
    identities = {
        r["deck_id"]: (r["deck_key"], r["source"], r["arena_deck_id"], r["deck_name"])
        for r in conn.execute("SELECT * FROM v_deck_identity")
    }
    assert identities[_MTGO_DECK] == (f"deck:{_MTGO_DECK}", "mtgo", None, "MTGO Deck")

    conn.execute("DELETE FROM mtgo_match_pick WHERE match_id = 'mtgo-picked'")
    conn.commit()
    assert _MTGO_DECK not in {
        r["deck_id"] for r in conn.execute("SELECT deck_id FROM v_deck_identity")
    }


def test_migration_050_deck_summary_counts_matches_only_under_their_deck(conn):
    """One row per deck and source: a deck with no match keeps a single row of
    zeros, and the unpicked and format-only MTGO matches, which have no deck,
    count under none."""
    _seed_pick_rows(conn)
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES ('unplayed-deck', 'Unplayed', '{}')"
    )
    conn.commit()

    summary = {
        (r["deck_id"], r["source"]): (r["matches_played"], r["matches_won"], r["last_played"])
        for r in conn.execute("SELECT * FROM v_deck_summary")
    }
    assert summary == {
        (_ARENA_DECK, "arena"): (1, 0, "2026-09-30T10:00:00"),
        (_MTGO_DECK, "mtgo"): (1, 1, "2026-09-30T11:00:00"),
        ("unplayed-deck", None): (0, 0, None),
    }


def test_migration_052_land_count_reads_the_unresolved_maindeck_count(conn):
    """MTGO decks carry the dropped copies in cards_json (0 included); an
    Arena deck has no such key and must read 0, not NULL. The count is the
    deck's own, not multiplied by its maindeck's size."""
    conn.execute(
        "INSERT INTO cards (grp_id, name, type_line) "
        "VALUES (1, 'Plains', 'Basic Land \u2014 Plains')"
    )
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES "
        "('arena', 'A', '{\"maindeck\": [1, 1, 1, 2]}'), "
        "('mtgo-whole', 'W', '{\"maindeck\": [1, 1], \"unresolved\": "
        "{\"maindeck\": 0, \"sideboard\": 4}}'), "
        "('mtgo-short', 'S', '{\"maindeck\": [1, 1, 1], \"unresolved\": "
        "{\"maindeck\": 5, \"sideboard\": 0}}')"
    )
    conn.commit()
    rows = {
        r["deck_id"]: (
            r["maindeck_size"], r["land_count"], r["unnamed_count"], r["unresolved_count"]
        )
        for r in conn.execute("SELECT * FROM v_deck_land_count")
    }
    assert rows == {
        "arena": (4, 3, 1, 0),
        "mtgo-whole": (2, 2, 0, 0),
        "mtgo-short": (3, 3, 0, 5),
    }


def test_deck_identity_names_a_guid_after_its_latest_played_version(conn):
    """Two versions of one Arena deck, renamed between them: the group takes
    the name of the version played last. The later version is the one whose
    deck_id sorts last and whose deck_guids row is older, and the earlier
    one has more matches, so neither the deck_id tie-break, the deck_guids
    order nor the match count picks its name."""
    conn.execute(
        "INSERT INTO decks (deck_id, name, cards_json) VALUES "
        "('a-old-version', 'Old Name', '{}'), ('b-new-version', 'New Name', '{}')"
    )
    conn.execute(
        "INSERT INTO deck_guids (deck_id, arena_deck_id, last_seen) VALUES "
        "('a-old-version', 'guid-1', '2026-09-20T00:00:00'), "
        "('b-new-version', 'guid-1', '2026-09-01T00:00:00')"
    )
    conn.execute(
        "INSERT INTO matches (match_id, deck_id, started_at, result) VALUES "
        "('old-1', 'a-old-version', '2026-09-02T10:00:00', 'win'), "
        "('old-2', 'a-old-version', '2026-09-03T10:00:00', 'win'), "
        "('new-1', 'b-new-version', '2026-09-04T10:00:00', 'loss')"
    )
    conn.commit()

    identities = {
        r["deck_id"]: (r["deck_key"], r["deck_name"])
        for r in conn.execute("SELECT * FROM v_deck_identity")
    }
    assert identities == {
        "a-old-version": ("guid:guid-1", "New Name"),
        "b-new-version": ("guid:guid-1", "New Name"),
    }


def test_migration_053_backfills_standard_legality_into_card_legality(tmp_path):
    """Frozen at 052 with cards that hold a Standard legality, migrate forward:
    each legal/not_legal/banned value becomes a 'Standard' row, and a card with
    NULL gets none (unknown, never a guess)."""
    conn = db.connect(tmp_path / "stuck_at_52.db")
    _migrate_to(conn, through_version=52)
    conn.executemany(
        "INSERT INTO cards (grp_id, name, standard_legality) VALUES (?, ?, ?)",
        [(1, "A", "legal"), (2, "B", "not_legal"), (3, "C", "banned"), (4, "D", None)],
    )
    conn.commit()

    assert 53 in db.migrate(conn)  # migrate() carries on through 054; 053's rows are read after

    rows = {
        r["grp_id"]: (r["format"], r["legality"])
        for r in conn.execute("SELECT grp_id, format, legality FROM card_legality")
    }
    assert rows == {
        1: ("Standard", "legal"),
        2: ("Standard", "not_legal"),
        3: ("Standard", "banned"),
    }
    conn.close()


def test_migration_054_drops_standard_legality_and_keeps_053s_rows(tmp_path):
    """Frozen at 052 with Standard values in the column, migrate forward through
    053 and 054: the column is gone, the card rows remain, and the rows 053
    backfilled into card_legality survive the drop."""
    conn = db.connect(tmp_path / "stuck_at_52.db")
    _migrate_to(conn, through_version=52)
    conn.executemany(
        "INSERT INTO cards (grp_id, name, standard_legality) VALUES (?, ?, ?)",
        [(1, "A", "legal"), (2, "B", "banned"), (3, "C", None)],
    )
    conn.commit()

    assert 54 in db.migrate(conn)

    columns = [r["name"] for r in conn.execute("PRAGMA table_info(cards)")]
    assert "standard_legality" not in columns
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 3
    rows = conn.execute(
        "SELECT grp_id, format, legality FROM card_legality ORDER BY grp_id"
    ).fetchall()
    assert [tuple(r) for r in rows] == [(1, "Standard", "legal"), (2, "Standard", "banned")]
    conn.close()


def test_migration_055_adds_a_nullable_checked_matches_format(tmp_path):
    """Frozen at 054 with a match, migrate forward: the column is NULL on the
    existing row, accepts one of the seven and refuses anything else."""
    conn = db.connect(tmp_path / "stuck_at_54.db")
    _migrate_to(conn, through_version=54)
    conn.execute("INSERT INTO matches (match_id) VALUES ('old')")
    conn.commit()

    assert 55 in db.migrate(conn)

    assert conn.execute("SELECT format FROM matches WHERE match_id = 'old'").fetchone()[0] is None
    conn.execute("INSERT INTO matches (match_id, format) VALUES ('new', 'Modern')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO matches (match_id, format) VALUES ('bad', 'Commander')")
    conn.close()


def test_migration_059_adds_a_nullable_checked_coach_report_format(tmp_path):
    """Frozen at 058 with a coach report, migrate forward: the column is NULL
    on the existing row (never backfilled), accepts one of the seven and
    refuses anything else."""
    conn = db.connect(tmp_path / "stuck_at_58.db")
    _migrate_to(conn, through_version=58)
    insert = (
        "INSERT INTO coach_report (generated_at, model, prompt, prose, sources_json, "
        "metrics_json, context_hash{col}) VALUES ('t', 'm', 'p', 'x', '[]', '{{}}', 'h'{val})"
    )
    conn.execute(insert.format(col="", val=""))
    conn.commit()

    assert 59 in db.migrate(conn)

    assert conn.execute("SELECT format FROM coach_report").fetchone()[0] is None
    conn.execute(insert.format(col=", format", val=", 'Modern'"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert.format(col=", format", val=", 'Commander'"))
    conn.close()


def test_migration_060_adds_a_nullable_card_events_mtgo_name(tmp_path):
    """Frozen at 059 with a card event, migrate forward: the column is NULL on
    the existing row (the next rebuild fills it, never the migration) and
    takes MTGO's transcript name on a new one."""
    conn = db.connect(tmp_path / "stuck_at_59.db")
    _migrate_to(conn, through_version=59)
    conn.execute("INSERT INTO matches (match_id, source) VALUES ('m', 'mtgo')")
    conn.execute("INSERT INTO games (match_id, game_number) VALUES ('m', 1)")
    insert = (
        "INSERT INTO card_events (match_id, game_number, seq, grp_id{col}) "
        "VALUES ('m', 1, ?, NULL{val})"
    )
    conn.execute(insert.format(col="", val=""), (1,))
    conn.commit()

    assert 60 in db.migrate(conn)

    assert conn.execute(
        "SELECT mtgo_name FROM card_events WHERE seq = 1"
    ).fetchone()[0] is None
    conn.execute(insert.format(col=", mtgo_name", val=", 'Map Token'"), (2,))
    assert conn.execute(
        "SELECT mtgo_name FROM card_events WHERE seq = 2"
    ).fetchone()[0] == "Map Token"
    conn.close()


def test_card_legality_rejects_an_unknown_format_or_value(conn):
    """The CHECKs are the only guard on the seven-format and four-value vocabularies."""
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO card_legality VALUES (1, 'Commander', 'legal')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO card_legality VALUES (1, 'Modern', 'maybe')")


def test_migration_061_adds_read_dates_and_the_fetch_hold(tmp_path):
    """Frozen at 060 with a corpus event, migrate forward: the event keeps NULL
    read dates (no backfill), and the CHECKs refuse values outside the
    vocabularies."""
    conn = db.connect(tmp_path / "stuck_at_60.db")
    _migrate_to(conn, through_version=60)
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, tier, standings_rows)"
        " VALUES ('e', 'e', 's', 'MTGO', 'E', 'C', 0)"
    )
    conn.commit()

    assert 61 in db.migrate(conn)

    assert tuple(conn.execute(
        "SELECT lists_read_at, empty_read_at, empty_read_kind FROM meta_event"
    ).fetchone()) == (None, None, None)
    conn.execute("UPDATE meta_event SET empty_read_kind = 'gone'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE meta_event SET empty_read_kind = 'missing'")
    hold = (
        "INSERT INTO meta_fetch_hold (source, status, http_status, answers, since,"
        " last_status, last_at) VALUES ('mtgo', ?, 503, 1, 't', 503, 't')"
    )
    conn.execute(hold, ("waiting",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(hold.replace("'mtgo'", "'other'"), ("held",))
    assert conn.execute("SELECT not_before FROM meta_fetch_hold").fetchone()[0] is None
    conn.close()
