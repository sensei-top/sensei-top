"""The events list and detail routes, and the hold on the status route
(``/api/metagame/events*``, ``/api/metagame/status``). Rows are inserted
in-test; every expectation is read off those rows or the plan's spec."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from sensei_top.api.app import create_app
from sensei_top.db import open_database
from sensei_top.metagame.holds import TIME_FORMAT


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "api.db"
    open_database(path).close()
    return path


@pytest.fixture
def client(db, make_client):
    with make_client(create_app(db)) as c:
        yield c


def _write(db, fn):
    import sqlite3

    conn = sqlite3.connect(db)
    fn(conn)
    conn.commit()
    conn.close()


def _event(conn, eid, name, date, tier="A", fmt="Modern", source="MTGO", dup=None):
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, format,"
        " tier, duplicate_of, uri, lists_read_at, empty_read_at, empty_read_kind)"
        " VALUES (?, 'p', 's', ?, ?, ?, ?, ?, ?, 'http://x/y', '2026-09-01T00:00:00Z',"
        " NULL, NULL)",
        (f"Tournaments/{eid}.json", source, name, date, fmt, tier, dup),
    )


def _deck(conn, eid, ord_, result=None, main=(), side=(), wl=(0, 0, 0), arch=None):
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, result, wins, losses, draws,"
        " mainboard_json, sideboard_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            f"Tournaments/{eid}.json", ord_, result, *wl,
            json.dumps([{"count": c, "name": n} for c, n in main]),
            json.dumps([{"count": c, "name": n} for c, n in side]),
        ),
    )
    if arch:
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name,"
            " colors, label, method, classified_at) VALUES (?, ?, ?, ?, 'WU', ?, 'archetype', 'n')",
            (f"Tournaments/{eid}.json", ord_, arch.lower(), arch, arch),
        )


def test_list_filters_order_and_row(db, client):
    def seed(c):
        _event(c, "MTGO/2026/09/02/b", "Beta", "2026-09-02T00:00:00Z")
        _event(c, "MTGO/2026/09/02/a", "Alpha", "2026-09-02T00:00:00Z")
        _event(c, "MTGO/2026/09/05/z", "Newest", "2026-09-05T00:00:00Z", tier="B")
        _event(c, "MTGO/2026/08/01/old", "Old", "2026-08-01T00:00:00Z")
        _event(c, "MTGO/2026/09/03/std", "Std", "2026-09-03T00:00:00Z", fmt="Standard")
        for path in ("MTGO/2026/09/02/b", "MTGO/2026/09/02/a", "MTGO/2026/09/05/z",
                     "MTGO/2026/08/01/old", "MTGO/2026/09/03/std"):
            _deck(c, path, 0, main=[(4, "X")])
        _deck(c, "MTGO/2026/09/05/z", 1, main=[])
    _write(db, seed)
    rows = client.get("/api/metagame/events?format=Modern&since=2026-08-15").json()
    assert [r["name"] for r in rows] == ["Newest", "Alpha", "Beta"]
    assert rows[0] == {
        "key": "MTGO/2026/09/05/z", "name": "Newest", "date": "2026-09-05", "format": "Modern",
        "tier": "B", "source": "MTGO", "lists": 1, "winner": None,
    }
    only_b = client.get("/api/metagame/events?format=Modern&since=2026-08-15&tier=B").json()
    assert [r["name"] for r in only_b] == ["Newest"]
    wide = client.get("/api/metagame/events?format=Modern&since=2026-07-01").json()
    assert wide[-1]["name"] == "Old"


def test_twins_and_deckless_hidden_and_404(db, client):
    def seed(c):
        _event(c, "MTGO/a", "Real", "2026-09-02")
        _deck(c, "MTGO/a", 0, main=[(1, "X")])
        _event(c, "MTGO/twin", "Twin", "2026-09-02", dup="Tournaments/MTGO/a.json")
        _deck(c, "MTGO/twin", 0, main=[(1, "X")])
        _event(c, "MTGO/empty", "Empty", "2026-09-02")
    _write(db, seed)
    rows = client.get("/api/metagame/events?format=Modern&since=2026-09-01").json()
    assert [r["key"] for r in rows] == ["MTGO/a"]
    assert client.get("/api/metagame/events/MTGO/a").status_code == 200
    for k in ("MTGO/twin", "MTGO/empty", "MTGO/nope"):
        assert client.get(f"/api/metagame/events/{k}").status_code == 404


def test_winner_is_lowest_ord_first_place(db, client):
    def seed(c):
        _event(c, "MTGO/w", "W", "2026-09-02")
        _deck(c, "MTGO/w", 0, result="2nd Place", arch="Second")
        _deck(c, "MTGO/w", 1, result="1st Place", arch="First")
        _deck(c, "MTGO/w", 2, result="1st Place", arch="Later")
        _event(c, "MTGO/n", "N", "2026-09-02")
        _deck(c, "MTGO/n", 0, result="5-0", arch="League")
    _write(db, seed)
    listed = client.get("/api/metagame/events?format=Modern&since=2026-09-01").json()
    rows = {r["key"]: r for r in listed}
    assert rows["MTGO/w"]["winner"] == "First"
    assert rows["MTGO/n"]["winner"] is None


def test_detail_groups_sideboard_record_archetype(db, client):
    def seed(c):
        for gid, name, tl in (
            (1, "Bear", "Creature — Bear"),
            (2, "Bolt", "Instant"),
            (3, "Vault", "Artifact Land"),
            (4, "Relic", "Artifact"),
            (5, "Walker Front // Land Back", "Creature — Human // Land"),
            (6, "Spell Front // Land Back", "Sorcery // Land"),
        ):
            c.execute("INSERT INTO cards (grp_id, name, type_line) VALUES (?, ?, ?)",
                      (gid, name, tl))
        _event(c, "MTGO/d", "D", "2026-09-02")
        _deck(c, "MTGO/d", 0, result="3rd Place", wl=(0, 0, 0),
              main=[(2, "Bear"), (4, "Bolt"), (3, "Vault"), (1, "Mystery"), (3, "Relic"),
                    (1, "Spell Front")],
              side=[(1, "Zed"), (3, "Yak"), (3, "Abe")])
        _deck(c, "MTGO/d", 1, result=None, wl=(4, 2, 1))
        _deck(c, "MTGO/d", 2, result="1st Place", arch="Winner")
    _write(db, seed)
    d = client.get("/api/metagame/events/MTGO/d").json()
    assert d["uri"] == "http://x/y" and d["date"] == "2026-09-02"
    assert d["lists_read_at"] == "2026-09-01T00:00:00Z" and d["empty_read_kind"] is None
    assert [x["placement"] for x in d["decks"]] == [1, 3, None]
    assert d["decks"][0]["archetype"] == {"key": "winner", "label": "Winner", "colors": "WU"}
    assert d["decks"][1]["archetype"] is None
    assert d["decks"][1]["record"] is None
    assert d["decks"][2]["record"] == {"wins": 4, "losses": 2, "draws": 1}
    third = d["decks"][1]
    groups = {g["type"]: g for g in third["main"]}
    assert [g["type"] for g in third["main"]] == ["Creature", "Instant", "Sorcery", "Artifact",
                                                   "Land", None]
    assert groups["Land"]["cards"] == [{"count": 3, "name": "Vault"}]
    assert groups["Artifact"]["cards"] == [{"count": 3, "name": "Relic"}]
    assert groups[None]["cards"] == [{"count": 1, "name": "Mystery"}]
    assert groups["Creature"]["count"] == 2
    assert third["side"] == [{"count": 3, "name": "Abe"}, {"count": 3, "name": "Yak"},
                             {"count": 1, "name": "Zed"}]


def test_mdfc_front_face_decides(db, client):
    def seed(c):
        c.execute("INSERT INTO cards (grp_id, name, type_line) VALUES (1, 'Front // Back',"
                  " 'Creature — Human // Land')")
        _event(c, "MTGO/m", "M", "2026-09-02")
        _deck(c, "MTGO/m", 0, main=[(2, "Front")])
    _write(db, seed)
    d = client.get("/api/metagame/events/MTGO/m").json()
    assert [g["type"] for g in d["decks"][0]["main"]] == ["Creature"]


def _hold(c, source, status, not_before):
    now = datetime.now(UTC)
    c.execute(
        "INSERT INTO meta_fetch_hold (source, status, http_status, answers, since, last_status,"
        " last_at, not_before) VALUES (?, ?, 429, 0, ?, 429, ?, ?)",
        (source, status, now.strftime(TIME_FORMAT), now.strftime(TIME_FORMAT), not_before),
    )


def _fmt(t):
    return t.strftime(TIME_FORMAT)


def test_status_hold_shown_hidden_and_without_fetch_row(db, client):
    soon = datetime.now(UTC) + timedelta(hours=2)
    past = datetime.now(UTC) - timedelta(hours=2)

    def seed(c):
        c.execute("INSERT INTO meta_fetch_source (source, fetched_at, events)"
                  " VALUES ('fbettega', '2026-09-01T00:00:00Z', 3)")
        _hold(c, "mtgo", "waiting", _fmt(soon))
        _hold(c, "topdeck", "waiting", _fmt(past))
    _write(db, seed)
    sources = {s["source"]: s for s in client.get("/api/metagame/status").json()["corpus_sources"]}
    assert sources["fbettega"]["hold"] is None
    assert sources["mtgo"]["hold"]["status"] == "waiting"
    assert sources["mtgo"]["hold"]["http_status"] == 429
    assert sources["mtgo"]["hold"]["not_before"] == _fmt(soon)
    assert sources["mtgo"]["events"] == 0 and sources["mtgo"]["age_hours"] is None
    assert "topdeck" not in sources


def _corpus_sources(client):
    return client.get("/api/metagame/status").json()["corpus_sources"]


def test_status_paused_hold_with_no_not_before_stored(db, client):
    _write(db, lambda c: _hold(c, "mtgo", "paused", None))
    hold = next(s for s in _corpus_sources(client) if s["source"] == "mtgo")["hold"]
    assert hold["status"] == "paused" and hold["not_before"] is None


def test_status_paused_hold_keeps_its_not_before(db, client):
    later = datetime.now(UTC) + timedelta(hours=5)
    _write(db, lambda c: _hold(c, "mtgo", "paused", _fmt(later)))
    hold = next(s for s in _corpus_sources(client) if s["source"] == "mtgo")["hold"]
    assert hold["status"] == "paused" and hold["not_before"] == _fmt(later)


def test_status_mtgo_fetch_row_carries_hold_once(db, client):
    soon = datetime.now(UTC) + timedelta(hours=2)

    def seed(c):
        c.execute("INSERT INTO meta_fetch_source (source, fetched_at, events)"
                  " VALUES ('mtgo', '2026-09-01T00:00:00Z', 4)")
        _hold(c, "mtgo", "waiting", _fmt(soon))
    _write(db, seed)
    rows = [s for s in _corpus_sources(client) if s["source"] == "mtgo"]
    assert len(rows) == 1
    assert rows[0]["events"] == 4 and rows[0]["hold"]["not_before"] == _fmt(soon)


def test_status_expired_hold_on_fetched_source_is_null(db, client):
    past = datetime.now(UTC) - timedelta(hours=1)

    def seed(c):
        c.execute("INSERT INTO meta_fetch_source (source, fetched_at, events)"
                  " VALUES ('mtgo', '2026-09-01T00:00:00Z', 4)")
        _hold(c, "mtgo", "waiting", _fmt(past))
    _write(db, seed)
    row = next(s for s in _corpus_sources(client) if s["source"] == "mtgo")
    assert row["hold"] is None


def test_card_order_within_group(db, client):
    def seed(c):
        for gid, name in enumerate(("Aaa", "Bbb", "Ccc", "Ddd"), start=1):
            c.execute("INSERT INTO cards (grp_id, name, type_line) VALUES (?, ?, 'Creature')",
                      (gid, name))
        _event(c, "MTGO/o", "O", "2026-09-02")
        _deck(c, "MTGO/o", 0, main=[(2, "Ccc"), (2, "Bbb"), (3, "Ddd"), (1, "Aaa")])
    _write(db, seed)
    group = client.get("/api/metagame/events/MTGO/o").json()["decks"][0]["main"][0]
    assert [(c["count"], c["name"]) for c in group["cards"]] == [
        (3, "Ddd"), (2, "Bbb"), (2, "Ccc"), (1, "Aaa"),
    ]


def test_list_event_id_tiebreak(db, client):
    def seed(c):
        for eid in ("MTGO/2/y", "MTGO/3/z", "MTGO/1/x"):
            _event(c, eid, "Same", "2026-09-02")
            _deck(c, eid, 0, main=[(1, "X")])
    _write(db, seed)
    rows = client.get("/api/metagame/events?format=Modern&since=2026-09-01").json()
    assert [r["key"] for r in rows] == ["MTGO/1/x", "MTGO/2/y", "MTGO/3/z"]


def test_list_days_window(db, client):
    today = datetime.now(UTC).date()
    inside = (today - timedelta(days=9)).isoformat()
    outside = (today - timedelta(days=12)).isoformat()

    def seed(c):
        _event(c, "MTGO/in", "In", inside)
        _event(c, "MTGO/out", "Out", outside)
        _deck(c, "MTGO/in", 0, main=[(1, "X")])
        _deck(c, "MTGO/out", 0, main=[(1, "X")])
    _write(db, seed)
    rows = client.get("/api/metagame/events?format=Modern&days=10").json()
    assert [r["name"] for r in rows] == ["In"]
