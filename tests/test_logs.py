"""The log file beside the database (``logs.py``, release plan 3, D10).

Every expectation here comes from D10 and the line format the plan fixes:
UTC times, an 8-hex-char session id per launch, WARNING and up (DEBUG with
``--verbose``), the home directory written as ``~``. The watcher child's
records reaching ``serve``'s file are tested against a real ``serve`` in
``test_live.py``, where its child runs.

Every ``main()`` here runs on a ``--db`` under ``tmp_path``, so its log file
lands there too; ``conftest.py`` points the config file at a temp directory
and takes off, after each test, the handlers ``main()`` installed.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import time
from datetime import UTC, datetime, timedelta
from importlib.metadata import version as package_version
from pathlib import Path

import pytest

from sensei_top import cli, logs
from sensei_top.llm import config as llm_config

LINE = re.compile(
    r"(?P<stamp>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3})Z (?P<session>[0-9a-f]{8}) "
    r"(?P<level>[A-Z]+) (?P<name>\S+): (?P<message>.*)"
)
HEADER = re.compile(
    r"started sensei-top (?P<version>\S+) \((?P<command>[\w-]+)\) on (?P<platform>.+), "
    r"Python (?P<python>\S+), database (?P<db>.+)"
)


@pytest.fixture
def far_from_utc():
    """Local time fourteen hours ahead of UTC (POSIX ``TZ`` writes the offset
    with its sign inverted), so a local timestamp can never pass for a UTC
    one. Windows has no ``tzset``: there the test holds against whatever zone
    the machine is in."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "<+14>-14"
    if hasattr(time, "tzset"):
        time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    if hasattr(time, "tzset"):
        time.tzset()


def run(tmp_path: Path, *argv: str) -> Path:
    """``main()`` on a database in ``tmp_path``; returns the log file's path."""
    cli.main(["--db", str(tmp_path / "t.db"), *argv])
    return tmp_path / "logs" / "sensei-top.log"


def lines(path: Path) -> list[re.Match[str]]:
    """Every line of the file that opens a record (a traceback's continuation
    lines do not)."""
    found = (LINE.fullmatch(line) for line in path.read_text(encoding="utf-8").splitlines())
    return [match for match in found if match is not None]


def headers(path: Path) -> list[tuple[re.Match[str], re.Match[str]]]:
    return [
        (line, header)
        for line in lines(path)
        if (header := HEADER.fullmatch(line["message"])) is not None
    ]


# --- the header line ----------------------------------------------------------


def test_the_first_line_names_the_launch_in_utc(tmp_path, monkeypatch, far_from_utc):
    """A file read beside a user's report has to compare across machines and
    across a DST change, so its times are UTC whatever the machine's zone.
    The header is INFO and still written, though the file takes WARNING and
    up: it is what says which launch the lines below belong to."""
    away = tmp_path / "elsewhere"  # a home the database is not under
    monkeypatch.setenv("HOME", str(away))
    monkeypatch.setenv("USERPROFILE", str(away))

    before = datetime.now(UTC)
    path = run(tmp_path, "config")
    after = datetime.now(UTC)

    first = lines(path)[0]
    header = HEADER.fullmatch(first["message"])
    assert header is not None, first.string
    assert (first["level"], first["name"]) == ("INFO", "sensei_top")
    stamp = datetime.strptime(first["stamp"], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)
    slack = timedelta(milliseconds=1)
    assert before - slack <= stamp <= after + slack
    assert header["version"] == package_version("sensei-top")
    assert header["command"] == "config"
    assert header["platform"] == platform.platform()
    assert header["python"] == platform.python_version()
    assert header["db"] == str((tmp_path / "t.db").resolve())


def test_every_line_carries_the_launchs_session(tmp_path):
    """``serve`` and a hand-run command append to one file; the session id is
    what tells their lines apart, so a record from any logger carries it."""
    path = run(tmp_path, "config")
    logging.getLogger("some.library").warning("a library's line")
    logging.getLogger("sensei_top.probe").warning("our own line")

    found = lines(path)
    assert [line["message"] for line in found[1:]] == ["a library's line", "our own line"]
    assert {line["session"] for line in found} == {found[0]["session"]}


@pytest.mark.parametrize("flag", ["--set-key", "--set-topdeck-key"])
def test_no_credential_reaches_the_file(tmp_path, flag):
    """``config --set-key KEY`` carries the key on argv, and ``--verbose``
    opens the file to every level: the key must reach the config file and
    nothing else. Then ``config`` reads it back, as a user checking it
    would."""
    key = "sk-dummy-0123456789abcdef-not-a-real-key"

    run(tmp_path, "--verbose", "config", flag, key)
    path = run(tmp_path, "--verbose", "config")

    assert key in llm_config.config_path().read_text(encoding="utf-8")
    assert [header["command"] for _, header in headers(path)] == ["config", "config"]
    for written in path.parent.iterdir():
        assert key not in written.read_text(encoding="utf-8", errors="replace")


# --- levels and launches -----------------------------------------------------


@pytest.mark.parametrize(
    ("verbose", "shown"),
    [(False, ["ERROR an error"]), (True, ["WARNING a warning", "ERROR an error"])],
)
def test_the_console_keeps_its_levels_and_the_file_takes_its_own(
    tmp_path, capsys, verbose, shown
):
    """The console showed ERROR, WARNING with ``--verbose``, before the file
    existed, and still does; the file takes WARNING, DEBUG with ``--verbose``.
    Neither handler's level may starve the other. pytest's own handlers are
    taken off for the call: with them on the root, ``install`` adds no
    console handler (``logs.py``, trap 4). They go back on afterwards:
    pytest adds its ``--log-file`` and ``--log-cli`` handlers once per
    session, not once per test."""
    root = logging.getLogger()
    pytest_handlers = root.handlers[:]
    for handler in pytest_handlers:
        root.removeHandler(handler)
    try:
        path = run(tmp_path, *(["--verbose"] if verbose else []), "config")
        capsys.readouterr()
        probe = logging.getLogger("sensei_top.probe")
        probe.debug("a debug line")
        probe.warning("a warning")
        probe.error("an error")
        console = capsys.readouterr().err.splitlines()
    finally:
        for handler in pytest_handlers:
            root.addHandler(handler)

    assert console == shown
    written = [line["message"] for line in lines(path)[1:]]
    expected = ["a warning", "an error"]
    assert written == (["a debug line", *expected] if verbose else expected)


def test_a_second_launch_replaces_the_first_rather_than_stacking(tmp_path):
    """Each ``main()`` in one process (one per test, or a script calling it
    twice) is a launch of its own: its own header, its own session, and one
    file handler, or every record would be written once per earlier call."""
    path = run(tmp_path, "config")
    logging.getLogger("sensei_top.probe").warning("first")
    run(tmp_path, "config")
    logging.getLogger("sensei_top.probe").warning("second")

    found = lines(path)
    first, second = (line["session"] for line, _ in headers(path))
    assert first != second
    by_message = {line["message"]: line["session"] for line in found}
    assert [line["message"] for line in found].count("second") == 1
    assert (by_message["first"], by_message["second"]) == (first, second)
    ours = os.path.abspath(path)
    writing = [h for h in logging.getLogger().handlers if getattr(h, "baseFilename", "") == ours]
    assert len(writing) == 1


# --- the home directory -------------------------------------------------------


def test_the_home_directory_is_written_as_a_tilde(tmp_path, monkeypatch):
    """A user attaches this file to a report; the home directory names them.
    The substitution runs on the formatted line, so a traceback's own copy of
    a path (``repr``, so doubled backslashes on Windows) is covered too."""
    home = tmp_path.resolve()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    path = run(tmp_path, "config")

    missing = home / "absent" / "notes.txt"
    try:
        missing.read_text()
    except OSError:
        logging.getLogger("sensei_top.probe").exception("could not read %s", missing)

    text = path.read_text(encoding="utf-8")
    [(_, header)] = headers(path)
    assert header["db"] == f"~{os.sep}t.db"
    assert f"could not read ~{os.sep}absent{os.sep}notes.txt" in text
    assert "Traceback" in text
    assert str(home) not in text
    assert repr(str(home))[1:-1] not in text


@pytest.mark.parametrize(
    ("line", "written"),
    [
        (r"database C:\Users\Sample\AppData\Local\sensei-top\sensei-top.db",
         r"database ~\AppData\Local\sensei-top\sensei-top.db"),
        ("database c:/users/SAMPLE/AppData", "database ~/AppData"),
        (r"No such file: 'C:\\Users\\Sample\\Player.log'", r"No such file: '~\\Player.log'"),
        (r"cd C:\Users\Sample", "cd ~"),
        (r"C:\Users\Sampler\x.db", r"C:\Users\Sampler\x.db"),
        (r"C:\Users\Sample.old\x.db", r"~.old\x.db"),
        (r"written to C:\Users\Sample.", "written to ~."),
    ],
)
def test_a_windows_home_matches_any_case_and_either_separator(line, written):
    """Windows paths compare without case, and reach a line with either
    separator, or doubled by ``repr`` in an ``OSError``. A longer name that
    only starts with the home's is someone else's directory; anything but a
    letter or digit after it still leaves the home's own name in the line,
    so it is written as ``~``."""
    pattern = logs._home_pattern(r"C:\Users\Sample", windows=True)
    assert pattern.sub("~", line) == written


@pytest.mark.parametrize(
    ("line", "written"),
    [
        ("database /home/sample/.local/share/sensei-top.db",
         "database ~/.local/share/sensei-top.db"),
        ("cd /home/sample", "cd ~"),
        ("/home/Sample/x.db", "/home/Sample/x.db"),
        ("/home/sampler/x.db", "/home/sampler/x.db"),
        ("/home/sample-old/x.db", "~-old/x.db"),
        ("written to /home/sample.", "written to ~."),
    ],
)
def test_a_posix_home_matches_exactly(line, written):
    """Case matters on Linux: ``/home/Sample`` is another directory. A full
    stop ending a sentence still leaves the home's name before it."""
    pattern = logs._home_pattern("/home/sample", windows=False)
    assert pattern.sub("~", line) == written


# --- rotation and failure ------------------------------------------------------


def refuse_renaming(monkeypatch, held: Path) -> dict[str, bool]:
    """Renaming ``held`` raises what Windows raises for a file another
    process holds open, for as long as the returned switch is on."""
    switch = {"on": True}
    target = os.path.abspath(held)

    def refuse(real):
        def move(src, dst, *args, **kwargs):
            if switch["on"] and os.path.abspath(src) == target:
                raise PermissionError(
                    13, "The process cannot access the file because it is being used", src
                )
            return real(src, dst, *args, **kwargs)

        return move

    monkeypatch.setattr(os, "replace", refuse(os.replace))
    monkeypatch.setattr(os, "rename", refuse(os.rename))
    return switch


def record(n: int) -> str:
    return f"record {n:02d} {'x' * 60}"


def test_a_refused_rotation_keeps_appending_to_the_current_file(tmp_path, monkeypatch, capsys):
    """On Windows a file another launch holds open cannot be renamed, and
    ``serve`` beside a hand-run command is exactly that. A refused rotation
    must lose nothing, push no backup off the end, and print no traceback
    for every record written while the file is over size; once the rename
    is allowed again, the next record rotates."""
    monkeypatch.setattr(logs, "MAX_BYTES", 1024)
    path = run(tmp_path, "config")
    refusing = refuse_renaming(monkeypatch, path)
    probe = logging.getLogger("sensei_top.probe")
    for n in range(40):
        probe.warning("%s", record(n))

    assert path.stat().st_size > 1024
    assert [p.name for p in path.parent.iterdir()] == ["sensei-top.log"]
    written = [line["message"] for line in lines(path)[1:]]
    assert written == [record(n) for n in range(40)]
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Logging error" not in err

    refusing["on"] = False
    probe.warning("after the other launch let go")
    assert [line["message"] for line in lines(path)] == ["after the other launch let go"]
    rotated = path.with_name("sensei-top.log.1")
    assert len(lines(rotated)) == 41


def test_a_refused_shift_puts_the_current_file_back(tmp_path, monkeypatch, capsys):
    """A launch that was writing the file when another one rotated it still
    holds what is now a backup, and on Windows that backup's rename is then
    refused, after the current file has already moved aside to make room.
    Left aside, the next rotation would move the next current file over it
    and lose it; it goes back to its own name instead, and keeps growing."""
    monkeypatch.setattr(logs, "MAX_BYTES", 1024)
    path = run(tmp_path, "config")
    backup = path.with_name("sensei-top.log.1")
    probe = logging.getLogger("sensei_top.probe")
    count = 0
    while not backup.exists():
        probe.warning("%s", record(count))
        count += 1
    refusing = refuse_renaming(monkeypatch, backup)
    for n in range(count, count + 40):
        probe.warning("%s", record(n))
    count += 40

    names = sorted(p.name for p in path.parent.iterdir())
    assert names == ["sensei-top.log", "sensei-top.log.1"]
    written = [line["message"] for name in (backup, path) for line in lines(name)]
    assert written[1:] == [record(n) for n in range(count)]
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Logging error" not in err

    refusing["on"] = False
    probe.warning("%s", record(count))
    names = sorted(p.name for p in path.parent.iterdir())
    assert names == ["sensei-top.log", "sensei-top.log.1", "sensei-top.log.2"]
    files = (path.with_name("sensei-top.log.2"), backup, path)
    written = [line["message"] for name in files for line in lines(name)]
    assert written[1:] == [record(n) for n in range(count + 1)]


def test_a_log_file_that_cannot_be_opened_does_not_stop_the_command(tmp_path, capsys):
    """Logging is never a reason a command fails: a file that cannot be
    opened is one console warning, and the command still does its work."""
    (tmp_path / "logs" / "sensei-top.log").mkdir(parents=True)

    run(tmp_path, "config")
    logging.getLogger("sensei_top.probe").warning("nowhere to write this")

    captured = capsys.readouterr()
    assert captured.out.strip()
    warned = [line for line in captured.err.splitlines() if line.strip()]
    assert len(warned) == 1
    assert warned[0].startswith("WARNING ")
