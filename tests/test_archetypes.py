"""Fetching and caching archetype definitions.

No network: every test builds the tar archive in memory, so what is exercised
is the extraction, the tolerant parse and the cache semantics — the parts that
have to survive whatever upstream ships.
"""

import io
import json
import tarfile

import pytest

from sensei_top.archetypes import source
from sensei_top.db import open_database


@pytest.fixture
def conn(tmp_path):
    c = open_database(tmp_path / "a.db")
    yield c
    c.close()


def archive(members: dict[str, str]) -> bytes:
    """A .tar.gz shaped like GitHub's, with its single top-level directory."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path, body in members.items():
            raw = body.encode("utf-8")
            info = tarfile.TarInfo(f"MTGOFormatData-main/{path}")
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


ARCHETYPE = json.dumps(
    {"Name": "Momo", "IncludeColorInName": True,
     "Conditions": [{"Type": "InMainboard", "Cards": ["Momo, Friendly Flier"]}]}
)
FALLBACK = json.dumps({"Name": "Control", "IncludeColorInName": False,
                       "CommonCards": ["Stock Up", "Negate"]})


# --- extraction -------------------------------------------------------------


def test_reads_archetypes_and_fallbacks(conn):
    files, skipped = source.read_archive(
        archive({
            "Formats/Standard/Archetypes/UWMomo.json": ARCHETYPE,
            "Formats/Standard/Fallbacks/Control.json": FALLBACK,
        })
    )
    assert skipped == 0
    assert {(f.kind, f.source, f.name) for f in files} == {
        ("archetype", "UWMomo", "Momo"),
        ("fallback", "Control", "Control"),
    }


def test_retired_format_folders_are_not_swept_in():
    """Upstream keeps rotated seasons beside the live format, so a prefix match
    on 'Standard' would load a metagame that no longer exists."""
    files, _ = source.read_archive(
        archive({
            "Formats/Standard/Archetypes/Live.json": ARCHETYPE,
            "Formats/Standard-20240803-20250730/Archetypes/Retired.json": ARCHETYPE,
        })
    )
    assert [f.source for f in files] == ["Live"]


def test_other_formats_are_ignored():
    files, _ = source.read_archive(
        archive({
            "Formats/Standard/Archetypes/Keep.json": ARCHETYPE,
            "Formats/Premodern/Archetypes/Skip.json": ARCHETYPE,
            "Formats/Modern-20240101-20250101/Archetypes/Retired.json": ARCHETYPE,
        })
    )
    assert [f.source for f in files] == ["Keep"]


def test_one_definition_per_format_when_a_name_repeats_across_formats(conn):
    files, skipped = source.read_archive(
        archive({
            "Formats/Modern/Archetypes/Affinity.json": ARCHETYPE,
            "Formats/Pauper/Archetypes/Affinity.json": ARCHETYPE,
        })
    )
    assert skipped == 0
    assert sorted((f.format, f.source) for f in files) == [
        ("Modern", "Affinity"), ("Pauper", "Affinity"),
    ]
    source.store_archetypes(conn, files)
    rows = conn.execute("SELECT format, source FROM archetypes ORDER BY format").fetchall()
    assert [(r["format"], r["source"]) for r in rows] == [
        ("Modern", "Affinity"), ("Pauper", "Affinity"),
    ]


def test_a_trailing_comma_still_parses():
    """Some files upstream ship trailing commas, which strict JSON refuses."""
    files, skipped = source.read_archive(
        archive({"Formats/Standard/Archetypes/Sloppy.json":
                 '{"Name": "Sloppy", "Conditions": [],}'})
    )
    assert skipped == 0
    assert [f.name for f in files] == ["Sloppy"]


def test_an_unparseable_file_is_skipped_not_fatal():
    """One bad file upstream must not cost the whole refresh."""
    files, skipped = source.read_archive(
        archive({
            "Formats/Standard/Archetypes/Good.json": ARCHETYPE,
            "Formats/Standard/Archetypes/Broken.json": "{ this is not json",
            "Formats/Standard/Archetypes/Nameless.json": '{"Conditions": []}',
        })
    )
    assert [f.source for f in files] == ["Good"]
    assert skipped == 2


# --- storage ----------------------------------------------------------------


def test_definitions_sharing_a_name_are_stored_separately(conn):
    """Upstream names repeat — two Standard fallbacks are both 'Midrange' — so
    the file stem is the identity, not the name."""
    files, _ = source.read_archive(
        archive({
            "Formats/Standard/Fallbacks/Bounce.json":
                json.dumps({"Name": "Midrange", "CommonCards": ["A"]}),
            "Formats/Standard/Fallbacks/Ramp.json":
                json.dumps({"Name": "Midrange", "CommonCards": ["B"]}),
        })
    )
    assert source.store_archetypes(conn, files) == 2
    assert conn.execute("SELECT COUNT(*) FROM archetypes").fetchone()[0] == 2


def test_storing_replaces_the_previous_fetch(conn):
    first, _ = source.read_archive(
        archive({"Formats/Standard/Archetypes/Old.json": ARCHETYPE})
    )
    source.store_archetypes(conn, first)
    second, _ = source.read_archive(
        archive({"Formats/Standard/Archetypes/New.json": ARCHETYPE})
    )
    source.store_archetypes(conn, second)
    rows = [r["source"] for r in conn.execute("SELECT source FROM archetypes")]
    assert rows == ["New"]


# --- refresh policy ---------------------------------------------------------


def test_a_fresh_cache_opens_no_socket(conn, monkeypatch):
    files, _ = source.read_archive(
        archive({"Formats/Standard/Archetypes/A.json": ARCHETYPE})
    )
    source.store_archetypes(conn, files)
    monkeypatch.setattr(
        source, "fetch_archive",
        lambda *a, **k: pytest.fail("a fresh cache must not hit the network"),
    )
    assert source.refresh_archetypes(conn).status == "fresh"


def test_a_failed_fetch_keeps_the_cached_copy(conn, monkeypatch):
    """Being offline must cost nothing: yesterday's definitions still name decks."""
    files, _ = source.read_archive(
        archive({"Formats/Standard/Archetypes/Cached.json": ARCHETYPE})
    )
    source.store_archetypes(conn, files)

    def boom(*args, **kwargs):
        raise OSError("no route to host")

    monkeypatch.setattr(source, "fetch_archive", boom)
    result = source.refresh_archetypes(conn, force=True)
    assert result.status == "failed"
    assert "no route to host" in (result.error or "")
    assert [r["source"] for r in conn.execute("SELECT source FROM archetypes")] == ["Cached"]


def test_a_failed_primary_fetch_tries_the_fallback_host(conn, monkeypatch):
    """Badaro's own sibling repos were both archived in 2025; MTGOFormatData
    itself is healthy but the fallback exists for exactly that pattern —
    the primary host failing outright, not a bad file."""

    def fetch(url, **kwargs):
        if url == source.ARCHIVE_URL:
            raise OSError("no route to host")
        assert url == source.FALLBACK_ARCHIVE_URL
        return archive({"Formats/Standard/Archetypes/FromFallback.json": ARCHETYPE})

    monkeypatch.setattr(source, "fetch_archive", fetch)
    result = source.refresh_archetypes(conn, force=True)
    assert result.status == "updated"
    row = conn.execute("SELECT url FROM archetype_fetch WHERE id = 1").fetchone()
    assert row["url"] == source.FALLBACK_ARCHIVE_URL
    assert [r["source"] for r in conn.execute("SELECT source FROM archetypes")] == ["FromFallback"]


def test_an_archive_without_our_format_does_not_wipe_the_cache(conn, monkeypatch):
    """Upstream renames its format folder when a season rotates. Replacing a
    working cache with nothing is strictly worse than being stale."""
    files, _ = source.read_archive(
        archive({"Formats/Standard/Archetypes/Cached.json": ARCHETYPE})
    )
    source.store_archetypes(conn, files)
    monkeypatch.setattr(
        source, "fetch_archive",
        lambda *a, **k: archive({"Formats/Premodern/Archetypes/Elsewhere.json": ARCHETYPE}),
    )
    assert source.refresh_archetypes(conn, force=True).status == "failed"
    assert [r["source"] for r in conn.execute("SELECT source FROM archetypes")] == ["Cached"]


def test_a_rotation_archive_still_updates_the_other_formats(conn, monkeypatch):
    """Only the Standard folder is renamed: the fetch holds Modern and no live
    Standard. It must replace Modern, keep Standard's cached rows, and report
    'updated' (the per-format DELETE in store_archetypes)."""
    files, _ = source.read_archive(
        archive({"Formats/Standard/Archetypes/Cached.json": ARCHETYPE})
    )
    source.store_archetypes(conn, files)
    monkeypatch.setattr(
        source, "fetch_archive",
        lambda *a, **k: archive({
            "Formats/Standard-20250101-20260101/Archetypes/Retired.json": ARCHETYPE,
            "Formats/Modern/Archetypes/Fresh.json": ARCHETYPE,
        }),
    )
    assert source.refresh_archetypes(conn, force=True).status == "updated"
    rows = {
        (r["format"], r["source"]) for r in conn.execute("SELECT format, source FROM archetypes")
    }
    assert rows == {("Standard", "Cached"), ("Modern", "Fresh")}


def test_a_rebuild_does_not_discard_downloaded_definitions(conn, monkeypatch):
    """Same rule as the card table: downloaded, not derived."""
    from sensei_top.projector.matches import project

    files, _ = source.read_archive(
        archive({"Formats/Standard/Archetypes/Kept.json": ARCHETYPE})
    )
    source.store_archetypes(conn, files)
    project(conn)
    assert conn.execute("SELECT COUNT(*) FROM archetypes").fetchone()[0] == 1
