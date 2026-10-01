"""The metagame corpus: tiering, fetching, and privacy.

No network: every test builds tree listings and event JSON in memory, in the
shape the findings document verified against real files on 2026-08-18 (see
mtg-data-sources-findings.md). What is exercised is selection, parsing, the
tier rule, and the incremental-refresh policy — the parts that have to
survive whatever upstream actually ships.
"""

import json
import shutil
import sqlite3
from dataclasses import asdict
from datetime import date

import pytest

from sensei_top import db
from sensei_top.db import open_database
from sensei_top.metagame import source
from sensei_top.metagame.classify_meta import classify_meta_decks
from sensei_top.metagame.dedup import mark_duplicate_events
from sensei_top.metagame.source import ParsedDeck, ParsedEvent, ParsedRoundMatch, TournamentFile
from sensei_top.metagame.tiers import classify_tier


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "m.db")
    yield c
    c.close()


# --- tiers -------------------------------------------------------------------
# Shapes read directly from real events (2026-08-18 findings document, and
# the 2026-09-29/30 corpus query behind the re-tier) — not synthesized to fit
# the rule. Ranking: paper 64+ (A), MTGO challenge (B), MTGO league (C),
# paper under 64 (D).


def test_a_40_player_paper_swiss_event_is_tier_d():
    """summer-wind-championship-standard-447528: 40 decks, 40 standings, 9
    full swiss rounds, 132 matches — a real swiss, but under 64 players."""
    item = {"Standings": [{}] * 40, "Rounds": [{"RoundName": f"Round {i}"} for i in range(9)]}
    assert classify_tier(item, "MTGmelee") == "D"


def test_an_mtgo_challenge_is_tier_b():
    """modern-challenge-64-2026-08-1712851686: 32 decks, 32 standings, but
    only 3 rounds — the published top-8 bracket, not the swiss that
    produced it. MTGO source alone decides B; round count plays no part."""
    item = {"Standings": [{}] * 32, "Rounds": [{"RoundName": r} for r in ("QF", "SF", "F")]}
    assert classify_tier(item, "MTGO") == "B"


def test_an_mtgo_league_is_tier_c():
    """standard-league-2026-08-1711015: 14 decks, every Result "5-0", zero
    standings, zero rounds — no losses anywhere in the file."""
    item = {"Standings": [], "Rounds": []}
    assert classify_tier(item, "MTGO") == "C"


def test_no_standings_is_tier_c_even_with_rounds_present():
    """Standings emptiness is the deciding signal, not round count alone —
    a malformed or partial file must degrade to the most conservative tier,
    whatever its source."""
    item = {"Standings": [], "Rounds": [{"RoundName": "R1"}] * 9}
    assert classify_tier(item, "MTGmelee") == "C"


def test_mit_championship_65_standings_is_tier_a():
    """Real corpus event (2026-09-29/30 query): a Melee paper event with 65
    standings rows clears the 64-player line."""
    item = {"Standings": [{}] * 65, "Rounds": []}
    assert classify_tier(item, "MTGmelee") == "A"


def test_an_lcq_with_63_standings_is_tier_d():
    """Real corpus event: one standings row short of the 64-player line."""
    item = {"Standings": [{}] * 63, "Rounds": []}
    assert classify_tier(item, "MTGmelee") == "D"


def test_a_13_player_recq_with_rounds_is_tier_d_not_a():
    """Real corpus event: 13 standings, 3 rounds — round count no longer
    promotes a small paper event to A the way the old shape-only rule did."""
    item = {"Standings": [{}] * 13, "Rounds": [{"RoundName": r} for r in ("R1", "R2", "R3")]}
    assert classify_tier(item, "MTGmelee") == "D"


def test_rc_dc_1198_standings_is_tier_a():
    """Real corpus event: a Regional Championship's Day Two, 1198 standings
    rows — the largest paper event in the corpus."""
    item = {"Standings": [{}] * 1198, "Rounds": []}
    assert classify_tier(item, "MTGmelee") == "A"


def test_mtgo_with_64_standings_is_still_tier_b():
    """Source alone decides B for an MTGO event with standings — clearing
    the 64-player line does not promote it to A, since MTGO never publishes
    a challenge's full swiss, only its top-32 bracket."""
    item = {"Standings": [{}] * 64, "Rounds": []}
    assert classify_tier(item, "MTGO") == "B"


def test_topdeck_with_no_standings_is_tier_c():
    """A Topdeck event is tabletop, but with no standings published it still
    degrades to the conservative tier like any other source."""
    item = {"Standings": [], "Rounds": []}
    assert classify_tier(item, "Topdeck") == "C"


# --- path selection ------------------------------------------------------------


def tree_entry(path: str, sha: str = "abc123") -> dict:
    return {"path": path, "type": "blob", "sha": sha}


def test_select_paths_keeps_only_configured_sources_in_window():
    tree = [
        tree_entry("Tournaments/MTGO/2026/08/15/standard-league-1.json"),
        tree_entry("Tournaments/MTGmelee/2026/08/16/standard-champs.json"),
        tree_entry("Tournaments/Topdeck/2026/08/16/standard-event.json"),  # dead source
        tree_entry("Tournaments/MTGO/2025/01/01/standard-old.json"),      # outside window
    ]
    selected = source.select_paths(
        tree, start=date(2026, 8, 1), end=date(2026, 8, 31), sources=("MTGO", "MTGmelee")
    )
    assert {f.path for f in selected} == {
        "Tournaments/MTGO/2026/08/15/standard-league-1.json",
        "Tournaments/MTGmelee/2026/08/16/standard-champs.json",
    }


def test_select_paths_drops_non_standard_filenames_before_fetching():
    tree = [
        tree_entry("Tournaments/MTGO/2026/08/15/modern-challenge-64.json"),
        tree_entry("Tournaments/MTGO/2026/08/15/standard-league.json"),
    ]
    selected = source.select_paths(tree, start=date(2026, 8, 1), end=date(2026, 8, 31))
    assert [f.path for f in selected] == ["Tournaments/MTGO/2026/08/15/standard-league.json"]


def test_select_paths_ignores_non_json_and_malformed_paths():
    tree = [
        {"path": "README.md", "type": "blob", "sha": "x"},
        {"path": "Tournaments/MTGO", "type": "tree", "sha": "y"},
        tree_entry("Tournaments/MTGO/notadate/08/15/standard-x.json"),
    ]
    assert source.select_paths(tree, start=date(2026, 1, 1), end=date(2026, 12, 31)) == []


def test_already_fetched_reports_stored_blob_shas(conn):
    event = ParsedEvent(
        event_id="Tournaments/MTGO/2026/08/15/standard-a.json",
        source="MTGO", name="A", event_date="2026-08-15", format="Standard", tier="C",
        standings_rows=0, uri=None, blob_sha="sha1",
    )
    source.store_events(conn, [event])
    assert source.already_fetched(conn) == {event.event_id: "sha1"}


# --- parsing -------------------------------------------------------------------


def _file(path="Tournaments/MTGO/2026/08/15/standard-a.json", sha="sha1") -> TournamentFile:
    return TournamentFile(path=path, blob_sha=sha)


def test_parse_event_never_retains_a_player_name():
    """The whole privacy rule: Player resolves matches to deck ordinals and
    is then simply gone."""
    raw = {
        "Tournament": {"Name": "Standard League", "Date": "2026-08-15", "Formats": "Standard"},
        "Decks": [
            {"Player": "RealHandle1", "Result": "5-0",
             "Mainboard": [{"Count": 4, "CardName": "Stock Up"}], "Sideboard": []},
            {"Player": "RealHandle2", "Result": "3-2",
             "Mainboard": [{"Count": 2, "CardName": "Negate"}], "Sideboard": []},
        ],
        "Rounds": [{"RoundName": "Round 1",
                     "Matches": [{"Player1": "RealHandle1", "Player2": "RealHandle2",
                                  "Result": "2-1-0"}]}],
        "Standings": [],
    }
    event = source.parse_event(raw, _file())
    assert event is not None
    dumped = json.dumps(
        {"decks": [asdict(d) for d in event.decks],
         "round_matches": [asdict(m) for m in event.round_matches]}
    )
    assert "RealHandle1" not in dumped
    assert "RealHandle2" not in dumped
    assert event.round_matches == [source.ParsedRoundMatch("Round 1", 0, 1, 2, 1, 0)]


def test_parse_event_normalizes_mainboard_casing_variants():
    raw = {
        "Tournament": {"Name": "T", "Formats": "Standard"},
        "Decks": [{"Player": "P", "Result": "5-0",
                   "Mainboard": [{"Count": 4, "CardName": "Stock Up"},
                                 {"count": 2, "card_name": "Negate"}],
                   "Sideboard": []}],
        "Rounds": [], "Standings": [],
    }
    event = source.parse_event(raw, _file())
    assert event is not None
    assert {(c["count"], c["name"]) for c in event.decks[0].mainboard} == {
        (4, "Stock Up"), (2, "Negate"),
    }


def test_parse_event_skips_a_match_whose_player_has_no_deck():
    """A bye, or a name that never appears in Decks[], cannot be expressed as
    a deck-to-deck matchup and must be dropped rather than guessed at."""
    raw = {
        "Tournament": {"Name": "T", "Formats": "Standard"},
        "Decks": [{"Player": "P", "Result": "2-0", "Mainboard": [], "Sideboard": []}],
        "Rounds": [{"RoundName": "R1",
                     "Matches": [{"Player1": "P", "Player2": "Bye", "Result": "2-0-0"}]}],
        "Standings": [],
    }
    event = source.parse_event(raw, _file())
    assert event is not None
    assert event.round_matches == []


def test_parse_event_tags_the_tier_from_shape():
    raw = {
        "Tournament": {"Name": "League", "Formats": "Standard"},
        "Decks": [{"Player": "P", "Result": "5-0", "Mainboard": [], "Sideboard": []}],
        "Rounds": [], "Standings": [],
    }
    event = source.parse_event(raw, _file())
    assert event is not None
    assert event.tier == "C"


def test_parse_event_rejects_a_non_standard_format():
    raw = {"Tournament": {"Name": "T", "Formats": ["Modern"]}, "Decks": [], "Rounds": [],
           "Standings": []}
    assert source.parse_event(raw, _file()) is None


def test_parse_event_accepts_formats_as_a_list_too():
    """The rest of this file's fixtures use the bare-string shape every real
    file inspected on 2026-08-18 (both MTGO and MTGmelee) actually carries —
    a list was the original, wrong assumption, caught only by running `meta`
    against the live cache (docs/testing.md's 'green tests are not proof').
    Both are accepted since nothing here guarantees upstream never varies it."""
    raw = {"Tournament": {"Name": "T", "Formats": ["Standard"]}, "Decks": [], "Rounds": [],
           "Standings": []}
    assert source.parse_event(raw, _file()) is not None


def test_parse_event_trusts_the_filename_prefilter_when_formats_is_absent():
    """No Formats block at all: the path-level 'standard' pre-filter already
    selected this file, so silence should not discard it."""
    raw = {"Tournament": {"Name": "T"}, "Decks": [], "Rounds": [], "Standings": []}
    assert source.parse_event(raw, _file()) is not None


def test_malformed_deck_records_degrade_to_zero_not_a_crash():
    raw = {
        "Tournament": {"Name": "T", "Formats": "Standard"},
        "Decks": [{"Player": "P", "Result": "garbage", "Mainboard": [], "Sideboard": []}],
        "Rounds": [], "Standings": [],
    }
    event = source.parse_event(raw, _file())
    assert event is not None
    assert (event.decks[0].wins, event.decks[0].losses, event.decks[0].draws) == (0, 0, 0)


def test_parse_event_prefers_standings_over_a_placement_string_result():
    """The real bug, caught by running `meta` against the live cache, not by
    a unit test: every real Tier A/B file's Decks[].Result is a placement
    string ("1st Place"), which _parse_record correctly can't read as a
    score. The real record lives in Standings[], resolved by Player name to
    the same deck_ord the round matches use."""
    raw = {
        "Tournament": {"Name": "T", "Formats": "Standard"},
        "Decks": [{"Player": "P", "Result": "1st Place", "Mainboard": [], "Sideboard": []}],
        "Rounds": [],
        "Standings": [{"Player": "P", "Wins": 6, "Losses": 2, "Draws": 1}],
    }
    event = source.parse_event(raw, _file())
    assert event is not None
    assert (event.decks[0].wins, event.decks[0].losses, event.decks[0].draws) == (6, 2, 1)


def test_parse_event_falls_back_to_result_when_standings_omits_a_deck():
    """A deck absent from Standings (or an event with none at all — Tier C,
    which never publishes one) still gets whatever `_parse_record` can read
    from Result directly."""
    raw = {
        "Tournament": {"Name": "T", "Formats": "Standard"},
        "Decks": [
            {"Player": "P1", "Result": "1st Place", "Mainboard": [], "Sideboard": []},
            {"Player": "P2", "Result": "3-2-0", "Mainboard": [], "Sideboard": []},
        ],
        "Rounds": [],
        "Standings": [{"Player": "P1", "Wins": 6, "Losses": 2, "Draws": 0}],
    }
    event = source.parse_event(raw, _file())
    assert event is not None
    assert (event.decks[0].wins, event.decks[0].losses, event.decks[0].draws) == (6, 2, 0)
    # P2 has no Standings row, so it falls back to parsing its own Result.
    assert (event.decks[1].wins, event.decks[1].losses, event.decks[1].draws) == (3, 2, 0)


# --- storage --------------------------------------------------------------------


def test_store_events_is_safe_to_re_run(conn):
    event = ParsedEvent(
        event_id="e1", source="MTGO", name="A", event_date="2026-08-15", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sha1",
        decks=[ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 1, "name": "X"}], [])],
    )
    assert source.store_events(conn, [event]) == 1
    assert source.store_events(conn, [event]) == 1
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM meta_deck").fetchone()[0] == 1


def test_storing_never_deletes_events_outside_this_batch(conn):
    """A window-limited refresh must not erase what an earlier, wider
    refresh already stored — unlike archetypes, which replaces by format."""
    older = ParsedEvent(
        event_id="older", source="MTGO", name="Old", event_date="2026-01-01", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sha0",
    )
    newer = ParsedEvent(
        event_id="newer", source="MTGO", name="New", event_date="2026-08-15", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sha1",
    )
    source.store_events(conn, [older])
    source.store_events(conn, [newer])
    ids = {r["event_id"] for r in conn.execute("SELECT event_id FROM meta_event")}
    assert ids == {"older", "newer"}


def test_a_rebuild_does_not_discard_the_metagame_corpus(conn):
    """Same rule as `archetypes` and `cards`: downloaded, not derived."""
    from sensei_top.projector.matches import project

    event = ParsedEvent(
        event_id="e1", source="MTGO", name="A", event_date="2026-08-15", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sha1",
    )
    source.store_events(conn, [event])
    project(conn)
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 1


# --- refresh policy ---------------------------------------------------------


def test_a_fresh_corpus_opens_no_socket(conn, monkeypatch):
    event = ParsedEvent(
        event_id="e1", source="MTGO", name="A", event_date="2026-08-15", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sha1",
    )
    source.store_events(conn, [event])
    conn.execute(
        "INSERT INTO meta_fetch (id, commit_sha, fetched_at, window_days, events, skipped) "
        "VALUES (1, 'deadbeef', strftime('%Y-%m-%dT%H:%M:%SZ','now'), 90, 1, 0)"
    )
    monkeypatch.setattr(
        source, "resolve_commit_sha",
        lambda *a, **k: pytest.fail("a fresh corpus must not hit the network"),
    )
    assert source.refresh_metagame(conn).status == "fresh"


def test_a_failed_fetch_keeps_the_cached_corpus(conn, monkeypatch):
    event = ParsedEvent(
        event_id="e1", source="MTGO", name="A", event_date="2026-08-15", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sha1",
    )
    source.store_events(conn, [event])

    def boom(*args, **kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(source, "resolve_commit_sha", boom)
    result = source.refresh_metagame(conn, force=True)
    assert result.status == "failed"
    assert "no route to host" in (result.error or "")
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 1


def test_refresh_skips_files_whose_blob_sha_is_unchanged(conn, monkeypatch):
    """Incremental by content: a refresh must not re-fetch a file that has
    not changed upstream, even inside the window."""
    stored = ParsedEvent(
        event_id="Tournaments/MTGO/2026/08/15/standard-a.json", source="MTGO", name="A",
        event_date="2026-08-15", format="Standard", tier="C", standings_rows=0, uri=None,
        blob_sha="unchanged-sha",
    )
    source.store_events(conn, [stored])

    tree = [tree_entry(stored.event_id, sha="unchanged-sha"),
            tree_entry("Tournaments/MTGO/2026/08/16/standard-b.json", sha="new-sha")]
    monkeypatch.setattr(source, "resolve_commit_sha", lambda *a, **k: "commit1")
    monkeypatch.setattr(source, "list_tree", lambda *a, **k: tree)

    fetched_paths = []

    def fake_fetch_event(commit_sha, path):
        fetched_paths.append(path)
        return {
            "Tournament": {"Name": "B", "Formats": "Standard"},
            "Decks": [{"Player": "P", "Result": "5-0", "Mainboard": [], "Sideboard": []}],
            "Rounds": [], "Standings": [],
        }

    monkeypatch.setattr(source, "fetch_event", fake_fetch_event)
    result = source.refresh_metagame(conn, force=True)
    assert result.status == "updated"
    assert fetched_paths == ["Tournaments/MTGO/2026/08/16/standard-b.json"]
    assert conn.execute("SELECT COUNT(*) FROM meta_event").fetchone()[0] == 2


def test_refresh_records_the_pinned_commit_sha(conn, monkeypatch):
    monkeypatch.setattr(source, "resolve_commit_sha", lambda *a, **k: "pinned-sha")
    monkeypatch.setattr(source, "list_tree", lambda *a, **k: [])
    result = source.refresh_metagame(conn, force=True)
    assert result.commit_sha == "pinned-sha"
    row = conn.execute("SELECT commit_sha FROM meta_fetch WHERE id = 1").fetchone()
    assert row["commit_sha"] == "pinned-sha"


def test_a_bad_file_upstream_is_skipped_not_fatal(conn, monkeypatch):
    monkeypatch.setattr(source, "resolve_commit_sha", lambda *a, **k: "commit1")
    monkeypatch.setattr(
        source, "list_tree",
        lambda *a, **k: [tree_entry("Tournaments/MTGO/2026/08/15/standard-broken.json")],
    )

    def boom(commit_sha, path):
        raise OSError("connection reset")

    monkeypatch.setattr(source, "fetch_event", boom)
    result = source.refresh_metagame(conn, force=True)
    assert result.status == "updated"
    assert result.events == 0
    assert result.skipped == 1


# --- classify_meta_decks and the views built on top -----------------------------
# One archetype (needs Momo), one fallback family, two events: a Tier C league
# (presence only) and a Tier A paper swiss with a real head-to-head match.


def _teach_meta(conn):
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'UWMomo', 'Momo', 0, ?, '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Momo",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]}]}),),
    )
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'Aristocrats', 'Aristocrats', 0, ?,"
        " '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Aristocrats",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Infestation Sage"]}]}),),
    )

    league = ParsedEvent(
        event_id="league1", source="MTGO", name="League", event_date="2026-08-01",
        format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="s1",
        decks=[
            ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "5-0", 5, 0, 0, [{"count": 4, "name": "Something Unmatched"}], []),
        ],
    )
    swiss = ParsedEvent(
        event_id="swiss1", source="MTGmelee", name="Champs", event_date="2026-08-10",
        format="Standard", tier="A", standings_rows=2, uri=None, blob_sha="s2",
        decks=[
            ParsedDeck(0, "2-1-0", 2, 1, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "1-2-0", 1, 2, 0, [{"count": 4, "name": "Infestation Sage"}], []),
        ],
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 2, 1, 0)],
    )
    source.store_events(conn, [league, swiss])


def test_classify_meta_decks_counts_survivors_and_eliminations(conn):
    _teach_meta(conn)
    counts = classify_meta_decks(conn)
    assert counts == {"classified": 3, "unclassified": 1, "skipped_format": 0}


def test_classify_meta_decks_is_a_full_rebuild(conn):
    """Re-running must not accumulate stale rows from a corpus that has
    since changed, same discipline as classify_matches."""
    _teach_meta(conn)
    classify_meta_decks(conn)
    classify_meta_decks(conn)
    assert conn.execute("SELECT COUNT(*) FROM meta_deck_archetype").fetchone()[0] == 3


def test_v_meta_presence_includes_every_tier(conn):
    _teach_meta(conn)
    classify_meta_decks(conn)
    rows = conn.execute("SELECT archetype_key, tier FROM v_meta_presence").fetchall()
    assert sorted((r["archetype_key"], r["tier"]) for r in rows) == sorted(
        [("UWMomo", "A"), ("Aristocrats", "A"), ("UWMomo", "C")]
    )


def test_v_meta_winrate_excludes_tier_c_leagues(conn):
    """The load-bearing constraint: a league event has no losses in it at
    all, so it must never contribute to a win rate — enforced in the view,
    not left as a convention."""
    _teach_meta(conn)
    classify_meta_decks(conn)
    tiers = {r["tier"] for r in conn.execute("SELECT DISTINCT tier FROM v_meta_winrate")}
    assert tiers == {"A"}
    assert conn.execute(
        "SELECT COUNT(*) FROM v_meta_winrate WHERE archetype_key = 'UWMomo' AND tier = 'C'"
    ).fetchone()[0] == 0


def test_v_meta_matchup_is_symmetric_with_sample_size(conn):
    _teach_meta(conn)
    classify_meta_decks(conn)
    rows = {
        (r["archetype_key"], r["opponent_key"]): r
        for r in conn.execute("SELECT * FROM v_meta_matchup")
    }
    momo_vs_aristo = rows[("UWMomo", "Aristocrats")]
    aristo_vs_momo = rows[("Aristocrats", "UWMomo")]
    assert momo_vs_aristo["n"] == 1
    assert momo_vs_aristo["matches_won"] == 1        # 2 games to 1
    assert aristo_vs_momo["matches_lost"] == 1
    assert momo_vs_aristo["games_won"] == 2
    assert aristo_vs_momo["games_won"] == 1


def _teach_meta_two_dated_swiss_events(conn):
    """Same archetype definitions as _teach_meta, but two Tier A swiss
    events on different dates for the same UWMomo-vs-Aristocrats pairing —
    built to exercise v_meta_matchup's event_date grain (044)."""
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'UWMomo', 'Momo', 0, ?, '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Momo",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]}]}),),
    )
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'Aristocrats', 'Aristocrats', 0, ?,"
        " '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Aristocrats",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Infestation Sage"]}]}),),
    )
    early = ParsedEvent(
        event_id="early", source="MTGmelee", name="Champs", event_date="2026-07-01",
        format="Standard", tier="A", standings_rows=2, uri=None, blob_sha="s1",
        decks=[
            ParsedDeck(0, "1-0-0", 1, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "0-1-0", 0, 1, 0, [{"count": 4, "name": "Infestation Sage"}], []),
        ],
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 1, 0, 0)],
    )
    late = ParsedEvent(
        event_id="late", source="MTGmelee", name="Champs", event_date="2026-08-10",
        format="Standard", tier="A", standings_rows=2, uri=None, blob_sha="s2",
        decks=[
            ParsedDeck(0, "1-0-0", 1, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
            ParsedDeck(1, "0-1-0", 0, 1, 0, [{"count": 4, "name": "Infestation Sage"}], []),
        ],
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 1, 0, 0)],
    )
    source.store_events(conn, [early, late])


def test_v_meta_matchup_carries_a_date_per_row(conn):
    """044_meta_matchup_date_grain.sql added event_date to v_meta_matchup's
    grain — 013's original comment claimed the matchup matrix would never
    need a date-window parameter, which is exactly the claim this migration
    corrects. Two events on different dates for the same archetype pairing
    must stay two separate rows, not collapse into one totalled row."""
    _teach_meta_two_dated_swiss_events(conn)
    classify_meta_decks(conn)
    rows = list(conn.execute(
        "SELECT * FROM v_meta_matchup WHERE archetype_key = 'UWMomo' "
        "AND opponent_key = 'Aristocrats'"
    ))
    assert sorted(r["event_date"] for r in rows) == ["2026-07-01", "2026-08-10"]
    assert all(r["n"] == 1 for r in rows)


def test_a_windowed_sum_over_v_meta_matchup_keeps_only_the_later_event(conn):
    """The whole point of the finer grain: a caller filtering
    ``event_date >= window_start`` must see only the post-window row's
    totals, not the pre-window one pooled in — the exact failure mode
    docs/metagame.md's "format-reset boundary" section warns about."""
    _teach_meta_two_dated_swiss_events(conn)
    classify_meta_decks(conn)
    windowed = conn.execute(
        "SELECT SUM(n) AS n, SUM(matches_won) AS matches_won FROM v_meta_matchup "
        "WHERE archetype_key = 'UWMomo' AND opponent_key = 'Aristocrats' "
        "AND event_date >= '2026-08-01'"
    ).fetchone()
    assert windowed["n"] == 1
    assert windowed["matches_won"] == 1

    unwindowed = conn.execute(
        "SELECT SUM(n) AS n FROM v_meta_matchup "
        "WHERE archetype_key = 'UWMomo' AND opponent_key = 'Aristocrats'"
    ).fetchone()
    assert unwindowed["n"] == 2


# --- mark_duplicate_events ----------------------------------------------------
# Shapes read from the real database (2026-09): 43 groups of identical events
# (35 pairs, 7 triples, 1 quadruple) — 52 surplus events, 1,338 surplus decks.
# 32 groups were Tier B challenges republished under a second path on the same
# date; the other 10 were Tier C leagues republished under a *later* date
# folder, with a different Tournament.Date too — which is why event_date
# cannot be part of the identity key.


def test_a_same_date_challenge_pair_marks_the_higher_id(conn):
    """The most common real shape (32 of 43 groups): a Tier B challenge
    republished under a second path, same event date."""
    decks = [
        ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], []),
        ParsedDeck(1, "3-2", 3, 2, 0, [{"count": 4, "name": "Infestation Sage"}], []),
    ]
    rounds = [ParsedRoundMatch("Round 1", 0, 1, 2, 1, 0)]
    a = ParsedEvent(
        event_id="chal-a", source="MTGO", name="Challenge", event_date="2026-08-15",
        format="Standard", tier="B", standings_rows=2, uri=None, blob_sha="sha-a",
        decks=decks, round_matches=rounds,
    )
    b = ParsedEvent(
        event_id="chal-b", source="MTGO", name="Challenge (mirror)", event_date="2026-08-15",
        format="Standard", tier="B", standings_rows=2, uri=None, blob_sha="sha-b",
        decks=decks, round_matches=rounds,
    )
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 1
    assert conn.execute(
        "SELECT duplicate_of FROM meta_event WHERE event_id = 'chal-b'"
    ).fetchone()["duplicate_of"] == "chal-a"
    assert conn.execute(
        "SELECT duplicate_of FROM meta_event WHERE event_id = 'chal-a'"
    ).fetchone()["duplicate_of"] is None
    assert conn.execute(
        "SELECT COUNT(*) FROM meta_deck WHERE event_id = 'chal-b'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM meta_round_match WHERE event_id = 'chal-b'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM meta_deck WHERE event_id = 'chal-a'"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM meta_round_match WHERE event_id = 'chal-a'"
    ).fetchone()[0] == 1


def test_a_league_republished_under_a_later_date_is_still_marked(conn):
    """The other real shape (10 of 43 groups): a Tier C league republished
    under a *later* date folder, with a different Tournament.Date too. This
    is the case that pins "no date in the key" — event_date differs and the
    survivor is still found."""
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], [])]
    survivor = ParsedEvent(
        event_id="Tournaments/MTGO/2026/06/08/standard-league-2026-06-0810660.json",
        source="MTGO", name="League", event_date="2026-06-08", format="Standard", tier="C",
        standings_rows=0, uri=None, blob_sha="sha-a", decks=decks,
    )
    twin = ParsedEvent(
        event_id="Tournaments/MTGO/2026/06/10/standard-league-2026-06-0810660.json",
        source="MTGO", name="League", event_date="2026-06-10", format="Standard", tier="C",
        standings_rows=0, uri=None, blob_sha="sha-b", decks=decks,
    )
    source.store_events(conn, [survivor, twin])
    assert mark_duplicate_events(conn) == 1
    row = conn.execute(
        "SELECT duplicate_of FROM meta_event WHERE event_id = ?", (twin.event_id,)
    ).fetchone()
    assert row["duplicate_of"] == survivor.event_id


def test_a_second_call_marks_nothing_more(conn):
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}], [])]
    a = ParsedEvent(event_id="a", source="MTGO", name="A", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sa",
                     decks=decks)
    b = ParsedEvent(event_id="b", source="MTGO", name="B", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sb",
                     decks=decks)
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 1
    before = dict(
        conn.execute("SELECT event_id, duplicate_of FROM meta_event").fetchall()
    )
    assert mark_duplicate_events(conn) == 0
    after = dict(conn.execute("SELECT event_id, duplicate_of FROM meta_event").fetchall())
    assert before == after


def test_a_sideboard_difference_prevents_a_merge(conn):
    a = ParsedEvent(
        event_id="sb-a", source="MTGO", name="A", event_date="2026-08-01", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sa",
        decks=[ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}],
                           [{"count": 1, "name": "Duress"}])],
    )
    b = ParsedEvent(
        event_id="sb-b", source="MTGO", name="B", event_date="2026-08-01", format="Standard",
        tier="C", standings_rows=0, uri=None, blob_sha="sb",
        decks=[ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}],
                           [{"count": 1, "name": "Negate"}])],
    )
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 0


def test_a_tier_difference_prevents_a_merge(conn):
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}], [])]
    a = ParsedEvent(event_id="tier-a", source="MTGO", name="A", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sa",
                     decks=decks)
    b = ParsedEvent(event_id="tier-b", source="MTGO", name="B", event_date="2026-08-01",
                     format="Standard", tier="B", standings_rows=1, uri=None, blob_sha="sb",
                     decks=decks)
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 0


def test_a_round_score_difference_prevents_a_merge(conn):
    decks = [
        ParsedDeck(0, "2-1-0", 2, 1, 0, [{"count": 4, "name": "X"}], []),
        ParsedDeck(1, "1-2-0", 1, 2, 0, [{"count": 4, "name": "Y"}], []),
    ]
    a = ParsedEvent(
        event_id="rd-a", source="MTGO", name="A", event_date="2026-08-01", format="Standard",
        tier="B", standings_rows=2, uri=None, blob_sha="sa", decks=decks,
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 2, 1, 0)],
    )
    b = ParsedEvent(
        event_id="rd-b", source="MTGO", name="B", event_date="2026-08-01", format="Standard",
        tier="B", standings_rows=2, uri=None, blob_sha="sb", decks=decks,
        round_matches=[ParsedRoundMatch("Round 1", 0, 1, 1, 2, 0)],
    )
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 0


def test_dedup_before_classify_counts_the_deck_once(conn):
    """The whole point of deleting a twin's rows rather than filtering them:
    classify_meta_decks and the presence view need no knowledge of
    duplicate_of at all to get this right."""
    conn.execute(
        "INSERT INTO archetypes (format, kind, source, name, include_color, definition, fetched_at)"
        " VALUES ('Standard', 'archetype', 'UWMomo', 'Momo', 0, ?, '2026-01-01T00:00:00Z')",
        (json.dumps({"Name": "Momo",
                     "Conditions": [{"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]}]}),),
    )
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "Momo, Friendly Flier"}], [])]
    a = ParsedEvent(event_id="league-a", source="MTGO", name="League", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sha-a",
                     decks=decks)
    b = ParsedEvent(event_id="league-b", source="MTGO", name="League (republished)",
                     event_date="2026-08-03", format="Standard", tier="C", standings_rows=0,
                     uri=None, blob_sha="sha-b", decks=decks)
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 1
    classify_meta_decks(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM meta_deck_archetype WHERE event_id = 'league-b'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM v_meta_presence WHERE archetype_key = 'UWMomo'"
    ).fetchone()[0] == 1


def test_chain_collapse_repoints_every_twin_at_a_new_lower_id_survivor(conn):
    """A newly fetched event with a lower id can take over as survivor from
    a group an earlier call already marked — every existing twin must be
    repointed at the new survivor, not left pointing at the old one."""
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}], [])]
    b = ParsedEvent(event_id="b", source="MTGO", name="B", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sb",
                     decks=decks)
    c = ParsedEvent(event_id="c", source="MTGO", name="C", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sc",
                     decks=decks)
    source.store_events(conn, [b, c])
    assert mark_duplicate_events(conn) == 1
    assert conn.execute(
        "SELECT duplicate_of FROM meta_event WHERE event_id = 'c'"
    ).fetchone()["duplicate_of"] == "b"

    a = ParsedEvent(event_id="a", source="MTGO", name="A", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sa",
                     decks=decks)
    source.store_events(conn, [a])
    assert mark_duplicate_events(conn) == 1  # only "b" transitions NULL -> marked
    rows = {
        r["event_id"]: r["duplicate_of"]
        for r in conn.execute("SELECT event_id, duplicate_of FROM meta_event")
    }
    assert rows["b"] == "a"
    assert rows["c"] == "a"


def test_restoring_a_survivor_clears_its_twins_blob_sha(conn):
    """When a survivor's file changes upstream, its twins were judged
    against content that no longer exists — clearing their blob_sha makes
    already_fetched report them as changed, so the next refresh re-judges
    them against the new content."""
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}], [])]
    a = ParsedEvent(event_id="a", source="MTGO", name="A", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sha-a1",
                     decks=decks)
    b = ParsedEvent(event_id="b", source="MTGO", name="B", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sha-b",
                     decks=decks)
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 1
    assert conn.execute(
        "SELECT duplicate_of FROM meta_event WHERE event_id = 'b'"
    ).fetchone()["duplicate_of"] == "a"

    a_updated = ParsedEvent(event_id="a", source="MTGO", name="A", event_date="2026-08-01",
                             format="Standard", tier="C", standings_rows=0, uri=None,
                             blob_sha="sha-a2", decks=decks)
    source.store_events(conn, [a_updated])
    row = conn.execute(
        "SELECT blob_sha, duplicate_of FROM meta_event WHERE event_id = 'b'"
    ).fetchone()
    assert row["blob_sha"] == ""
    assert row["duplicate_of"] == "a"  # b itself was not re-fetched
    assert source.already_fetched(conn)["b"] == ""


def test_restoring_a_twin_resets_its_duplicate_of_to_null(conn):
    """A re-fetched file is judged afresh — store_events must not leave a
    stale duplicate_of pointing at a verdict reached over content that may
    no longer be there."""
    decks = [ParsedDeck(0, "5-0", 5, 0, 0, [{"count": 4, "name": "X"}], [])]
    a = ParsedEvent(event_id="a", source="MTGO", name="A", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sha-a",
                     decks=decks)
    b = ParsedEvent(event_id="b", source="MTGO", name="B", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sha-b1",
                     decks=decks)
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 1

    b_refetched = ParsedEvent(event_id="b", source="MTGO", name="B", event_date="2026-08-01",
                               format="Standard", tier="C", standings_rows=0, uri=None,
                               blob_sha="sha-b2", decks=decks)
    source.store_events(conn, [b_refetched])
    assert conn.execute(
        "SELECT duplicate_of FROM meta_event WHERE event_id = 'b'"
    ).fetchone()["duplicate_of"] is None


def test_an_event_with_no_decks_is_never_marked(conn):
    """Candidates require at least one meta_deck row — otherwise every empty
    event would share one key and be merged with every other empty one."""
    a = ParsedEvent(event_id="empty-a", source="MTGO", name="A", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sa")
    b = ParsedEvent(event_id="empty-b", source="MTGO", name="B", event_date="2026-08-01",
                     format="Standard", tier="C", standings_rows=0, uri=None, blob_sha="sb")
    source.store_events(conn, [a, b])
    assert mark_duplicate_events(conn) == 0
    for event_id in ("empty-a", "empty-b"):
        assert conn.execute(
            "SELECT duplicate_of FROM meta_event WHERE event_id = ?", (event_id,)
        ).fetchone()["duplicate_of"] is None


# --- migration 047: the tier re-rank ---------------------------------------------


def test_migration_047_reranks_tiers_from_stored_columns(tmp_path):
    """Freeze a database at schema 46 (the old 3-letter CHECK), insert one
    event per old shape exactly as `classify_tier` used to tag it — an MTGO
    league, an MTGO challenge, and three Melee paper swisses shaped like real
    corpus events (2026-09-29/30 query): a 1198-standings Regional
    Championship Day Two, a 40-standings/9-round event tagged 'A' under the
    old round-count rule, and a 13-standings/3-round event tagged 'B' under
    the same old rule. Migrating forward must recompute every one from
    `standings_rows`/`source` alone: unchanged for the two MTGO events, but
    the two smaller Melee events drop from 'A'/'B' to 'D' now that round
    count no longer promotes a small paper swiss."""
    old_migrations = tmp_path / "old_migrations"
    old_migrations.mkdir()
    for version, path in db.discover_migrations():
        if version <= 46:
            shutil.copy(path, old_migrations / path.name)

    conn = db.connect(tmp_path / "rerank.db")
    db.migrate(conn, old_migrations)
    assert db.applied_version(conn) == 46

    rows = [
        # (event_id, source, standings_rows, old tier)
        ("league", "MTGO", 0, "C"),
        ("challenge", "MTGO", 32, "B"),
        ("swiss-1198", "MTGmelee", 1198, "A"),
        ("swiss-40", "MTGmelee", 40, "A"),
        ("bracket-13", "MTGmelee", 13, "B"),
    ]
    for event_id, evt_source, standings_rows, old_tier in rows:
        conn.execute(
            "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
            "format, tier, standings_rows, uri) VALUES (?, ?, ?, ?, ?, '2026-08-01', "
            "'Standard', ?, ?, NULL)",
            (event_id, f"Tournaments/{evt_source}/{event_id}.json", event_id, evt_source,
             event_id, old_tier, standings_rows),
        )
    conn.commit()

    applied = db.migrate(conn)
    assert 47 in applied

    tiers = dict(conn.execute("SELECT event_id, tier FROM meta_event"))
    assert tiers == {
        "league": "C",
        "challenge": "B",
        "swiss-1198": "A",
        "swiss-40": "D",
        "bracket-13": "D",
    }

    # The CHECK constraint accepts 'D' and rejects an unknown letter.
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier, standings_rows, uri) VALUES ('ok-d', 'x', 'y', 'MTGmelee', 'x', "
        "NULL, NULL, 'D', 10, NULL)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
            "format, tier, standings_rows, uri) VALUES ('bad', 'x', 'z', 'MTGO', 'x', "
            "NULL, NULL, 'E', 0, NULL)"
        )

    view_names = {
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view' AND name LIKE 'v_meta_%'"
        )
    }
    assert view_names == {"v_meta_presence", "v_meta_winrate", "v_meta_matchup"}

    # One deck+archetype row on the Tier C league and one on the (now) Tier D
    # small swiss, so v_meta_winrate has something to include or exclude.
    for event_id in ("league", "swiss-40"):
        conn.execute(
            "INSERT INTO meta_deck (event_id, deck_ord, result, wins, losses, draws, "
            "mainboard_json, sideboard_json) VALUES (?, 0, '5-0', 5, 0, 0, '[]', '[]')",
            (event_id,),
        )
        conn.execute(
            "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, "
            "archetype_name, colors, label, method, classified_at) VALUES "
            "(?, 0, 'X', 'X', NULL, 'X', 'fallback', '2026-01-01T00:00:00Z')",
            (event_id,),
        )
    conn.commit()

    presence_tiers = {r[0] for r in conn.execute("SELECT DISTINCT tier FROM v_meta_presence")}
    assert presence_tiers == {"C", "D"}

    winrate_tiers = {r[0] for r in conn.execute("SELECT DISTINCT tier FROM v_meta_winrate")}
    assert winrate_tiers == {"D"}
    conn.close()
