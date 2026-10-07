"""MTGO folder discovery and its suggestion (release plan 3, D8).

Windows behaviour is simulated on any host by patching ``sys.platform`` and
``LOCALAPPDATA`` into ``tmp_path`` trees; creation time cannot be set on
Linux, so ``_created`` is patched to read a map. The one real-creation-time
test runs only on Windows.
"""

import os
import sys
from pathlib import Path

import pytest

from sensei_top.mtgo import discover

NAME = "Match_GameLog_20260101abc.dat"


def _folder(root: Path, name: str, *, mtime: float | None = None, logs: bool = True) -> Path:
    folder = root / "Apps" / "2.0" / "Data" / name / "Data" / "Logs"
    folder.mkdir(parents=True)
    if logs:
        log = folder / NAME
        log.write_bytes(b"x")
        if mtime is not None:
            os.utime(log, (mtime, mtime))
    else:
        (folder / "other.txt").write_text("x")
    return folder


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(discover.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


def _created_by_name(monkeypatch, order: list[Path]):
    monkeypatch.setattr(discover, "_created", lambda p: float(order.index(p)))


def test_discovery_picks_the_folder_created_last(windows, monkeypatch):
    old = _folder(windows, "aaa")
    new = _folder(windows, "bbb")
    _folder(windows, "ccc", logs=False)
    _created_by_name(monkeypatch, [old, new])  # later in the list = created later
    assert discover.discover_log_folder() == new


def test_discovery_is_none_when_no_folder_holds_a_log(windows):
    _folder(windows, "aaa", logs=False)
    assert discover.discover_log_folder() is None


def test_discovery_is_none_when_the_apps_tree_is_missing(windows):
    assert discover.discover_log_folder() is None


def test_discovery_is_none_off_windows(monkeypatch, tmp_path):
    _folder(tmp_path, "aaa")
    monkeypatch.setattr(discover.sys, "platform", "linux")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert discover.discover_log_folder() is None


def test_discovery_is_none_without_localappdata(monkeypatch):
    monkeypatch.setattr(discover.sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert discover.discover_log_folder() is None


def test_case_a_nothing_configured_names_the_folder(tmp_path):
    folder = tmp_path / "found"
    assert discover.suggestion(None, folder) == (
        "MTGO writes its game logs to a folder that isn't configured yet. To read them, run:\n"
        f'  sensei-top config --set-mtgo-dir "{folder}"'
    )


def test_case_b_configured_folder_is_behind(tmp_path):
    configured = _folder(tmp_path / "c", "a", mtime=1_000)
    found = _folder(tmp_path / "d", "b", mtime=2_000)
    assert discover.suggestion(configured, found) == (
        f"MTGO's newest game logs are in a different folder from {configured}: "
        "it moves the folder when it updates. To read them, run:\n"
        f'  sensei-top config --set-mtgo-dir "{found}"'
    )


def test_case_b_configured_folder_missing_or_empty(tmp_path):
    found = _folder(tmp_path / "d", "b", mtime=2_000)
    missing = tmp_path / "gone"
    empty = _folder(tmp_path / "e", "c", logs=False)
    assert discover.suggestion(missing, found) is not None
    assert discover.suggestion(empty, found) is not None


def test_no_suggestion_when_nothing_was_discovered(tmp_path):
    assert discover.suggestion(None, None) is None
    assert discover.suggestion(tmp_path, None) is None


def test_no_suggestion_when_configured_is_the_discovered_folder(tmp_path):
    folder = _folder(tmp_path, "a", mtime=1_000)
    assert discover.suggestion(folder, folder) is None


def test_no_suggestion_when_configured_is_as_new_or_newer(tmp_path):
    configured = _folder(tmp_path / "c", "a", mtime=3_000)
    found_same = _folder(tmp_path / "d", "b", mtime=3_000)
    found_older = _folder(tmp_path / "e", "b", mtime=2_000)
    assert discover.suggestion(configured, found_same) is None
    assert discover.suggestion(configured, found_older) is None


def test_paths_compare_case_insensitively_on_windows(monkeypatch, tmp_path):
    folder = _folder(tmp_path, "a", mtime=1_000)
    monkeypatch.setattr(discover.sys, "platform", "win32")
    assert discover._same_folder(folder, Path(str(folder).swapcase()))


def test_case_b_prime_points_at_the_variable_when_it_is_the_source(tmp_path):
    configured = _folder(tmp_path / "c", "a", mtime=1_000)
    found = _folder(tmp_path / "d", "b", mtime=2_000)
    assert discover.suggestion(configured, found, "$MTGO_LOG_DIR") == (
        f"MTGO's newest game logs are in a different folder from {configured}: "
        "it moves the folder when it updates. To read them, point MTGO_LOG_DIR at:\n"
        f"  {found}"
    )
    # The config file's source keeps case B's command.
    assert "config --set-mtgo-dir" in discover.suggestion(
        configured, found, "config.toml [mtgo] dir"
    )


def test_case_b_prime_is_silent_when_not_behind(tmp_path):
    configured = _folder(tmp_path / "c", "a", mtime=3_000)
    found = _folder(tmp_path / "d", "b", mtime=2_000)
    assert discover.suggestion(configured, found, "$MTGO_LOG_DIR") is None


@pytest.mark.skipif(sys.platform != "win32", reason="real creation time is the Windows measure")
def test_real_creation_time_orders_folders_on_windows(monkeypatch, tmp_path):
    import time

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    _folder(tmp_path, "aaa")
    time.sleep(0.05)
    newer = _folder(tmp_path, "bbb")
    assert discover.discover_log_folder() == newer
