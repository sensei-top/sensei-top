"""Arena's install directory, from the ``Mono path[0]`` line that opens its log.

The gap this closes: only a Steam install's card database was ever found, so
Wizards' installer and Epic fell back to Scryfall. The line's shape is the one
verified on a real Steam/Proton log: ``Mono path[0] = '<install>/MTGA_Data/
Managed'``. Under Proton it is a Wine path, mapped through the prefix's
``dosdevices/``; Windows has no ``dosdevices/`` and no ``:`` in a file name,
so those cases run off Windows only.
"""

import os
import sys
from pathlib import Path

import pytest

from sensei_top.arena_install import install_dir
from sensei_top.cards import arena_card_database_path

# Where the log sits inside a Wine prefix (the Proton layout, reader/ingest.py).
PREFIX_LOG = "drive_c/users/steamuser/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log"
CARD_DB = "MTGA_Data/Downloads/Raw/Raw_CardDatabase_abc123.mtga"

no_wine_on_windows = pytest.mark.skipif(
    sys.platform == "win32", reason="dosdevices names hold ':', which Windows forbids"
)


def write_log(path: Path, managed: str, terminator: str = "\r\n") -> Path:
    """A log whose line 1 names ``managed``. Line 2 holds a quote of its own,
    so a first line that ran on into it would no longer end in the Mono
    path's closing quote."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        f"Mono path[0] = '{managed}'{terminator}Second line = 'not the install'\r\n".encode()
    )
    return path


def make_install(folder: Path) -> Path:
    (folder / "MTGA_Data/Managed").mkdir(parents=True)
    return folder


@pytest.fixture
def prefix(tmp_path: Path) -> Path:
    """A Wine prefix as Proton lays one out: ``c:`` points at ``../drive_c``."""
    pfx = tmp_path / "compatdata/2141910/pfx"
    (pfx / "drive_c").mkdir(parents=True)
    (pfx / "dosdevices").mkdir()
    (pfx / "dosdevices/c:").symlink_to("../drive_c", target_is_directory=True)
    return pfx


# --- Wine paths ---------------------------------------------------------------


@no_wine_on_windows
def test_a_c_drive_path_resolves_through_the_prefix(prefix):
    install = make_install(prefix / "drive_c/Program Files/Wizards of the Coast/MTGA")
    log_path = write_log(
        prefix / PREFIX_LOG, "C:/Program Files/Wizards of the Coast/MTGA/MTGA_Data/Managed"
    )
    assert install_dir(log_path) == install.resolve()


@no_wine_on_windows
def test_a_z_drive_path_resolves_through_the_prefix(prefix, tmp_path):
    """Wine's ``z:`` is the host's root; here a stand-in folder for it."""
    host_root = tmp_path / "host-root"
    host_root.mkdir()
    (prefix / "dosdevices/z:").symlink_to(host_root, target_is_directory=True)
    install = make_install(host_root / "games/SteamLibrary/steamapps/common/MTGA")
    log_path = write_log(
        prefix / PREFIX_LOG, "Z:/games/SteamLibrary/steamapps/common/MTGA/MTGA_Data/Managed"
    )
    assert install_dir(log_path) == install.resolve()


@no_wine_on_windows
def test_a_drive_the_prefix_does_not_map_is_none(prefix):
    make_install(prefix / "drive_c/MTGA")
    log_path = write_log(prefix / PREFIX_LOG, "D:/MTGA/MTGA_Data/Managed")
    assert install_dir(log_path) is None


@no_wine_on_windows
def test_a_wine_path_in_a_log_outside_any_prefix_is_none(monkeypatch, tmp_path):
    """A log copied out of its prefix: the drive letter maps to nothing, and
    is never read as a host path, here one relative to the working folder."""
    monkeypatch.chdir(tmp_path)
    make_install(tmp_path / "C:/MTGA")
    log_path = write_log(tmp_path / "copied/Player.log", "C:/MTGA/MTGA_Data/Managed")
    assert install_dir(log_path) is None


# --- native paths and the first line ---------------------------------------------


@pytest.mark.parametrize("terminator", ["\r\n", "\n", "\r"], ids=["crlf", "lf", "bare-cr"])
def test_a_native_path_is_taken_as_written(tmp_path, terminator):
    """A Windows install's own path on Windows. The log mixes CRLF with bare
    CR, so line 1 ends at either."""
    install = make_install(tmp_path / "Wizards of the Coast/MTGA")
    log_path = write_log(
        tmp_path / "logs/Player.log", f"{install.as_posix()}/MTGA_Data/Managed", terminator
    )
    assert install_dir(log_path) == install.resolve()


@pytest.mark.parametrize(
    "line",
    [
        "",
        "[UnityCrossThreadLogger]==> GetFormats {}",
        "Mono path[0] = '{install}/Managed'",
        "Mono path[0] = '{install}/Gone/MTGA_Data/Managed'",
    ],
    ids=["blank", "not-the-mono-line", "no-mtga-data", "install-gone"],
)
def test_a_first_line_that_names_no_install_is_none(tmp_path, line):
    install = make_install(tmp_path / "MTGA")
    log_path = tmp_path / "Player.log"
    log_path.write_text(line.replace("{install}", install.as_posix()) + "\r\n", encoding="utf-8")
    assert install_dir(log_path) is None


def test_no_log_or_an_empty_one_is_none(tmp_path):
    """Empty is a log Arena has just truncated on launch."""
    assert install_dir(None) is None
    assert install_dir(tmp_path / "Player.log") is None
    (tmp_path / "Player.log").write_bytes(b"")
    assert install_dir(tmp_path / "Player.log") is None


# --- the card database ----------------------------------------------------------


def test_the_card_database_comes_from_the_install_the_log_names(
    monkeypatch, tmp_path, steam_libraries
):
    """Tried before the Steam glob, newer copy or not: it is the client that
    wrote the log."""
    install = make_install(tmp_path / "Wizards of the Coast/MTGA")
    (install / CARD_DB).parent.mkdir(parents=True)
    (install / CARD_DB).write_text("")
    log_path = write_log(tmp_path / "logs/Player.log", f"{install.as_posix()}/MTGA_Data/Managed")
    monkeypatch.setenv("MTGA_LOG", str(log_path))

    default_steam, _ = steam_libraries
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (default_steam,))
    steam_copy = default_steam / "steamapps/common/MTGA" / CARD_DB
    steam_copy.parent.mkdir(parents=True)
    steam_copy.write_text("")
    later = (install / CARD_DB).stat().st_mtime + 60
    os.utime(steam_copy, (later, later))

    assert arena_card_database_path() == (install / CARD_DB).resolve()


def test_the_steam_glob_still_answers_when_the_log_names_no_install(
    monkeypatch, tmp_path, steam_libraries
):
    log_path = tmp_path / "logs/Player.log"
    log_path.parent.mkdir(parents=True)
    log_path.write_text("")  # Arena truncated it on launch: no line 1 yet
    monkeypatch.setenv("MTGA_LOG", str(log_path))

    default_steam, _ = steam_libraries
    monkeypatch.setattr("sensei_top.steam.STEAM_DATA_DIRS", (default_steam,))
    steam_copy = default_steam / "steamapps/common/MTGA" / CARD_DB
    steam_copy.parent.mkdir(parents=True)
    steam_copy.write_text("")

    assert arena_card_database_path() == steam_copy
