"""The generate call's cost line reaches the console and the log file
(``logs.py``). Split from ``tests/test_logs.py``, whose docstring has the
line format; this one needs ``ai/`` for the logger's name.
"""

from __future__ import annotations

import contextlib
import logging
import re
from pathlib import Path

import pytest

from sensei_top import cli
from sensei_top.ai.llm import client as llm_client

LINE = re.compile(
    r"(?P<stamp>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3})Z (?P<session>[0-9a-f]{8}) "
    r"(?P<level>[A-Z]+) (?P<name>\S+): (?P<message>.*)"
)


def run(tmp_path: Path, *argv: str) -> Path:
    """``main()`` on a database in ``tmp_path``; returns the log file's path."""
    cli.main(["--db", str(tmp_path / "t.db"), *argv])
    return tmp_path / "logs" / "sensei-top.log"


def lines(path: Path) -> list[re.Match[str]]:
    """Every line of the file that opens a record (a traceback's continuation
    lines do not)."""
    found = (LINE.fullmatch(line) for line in path.read_text(encoding="utf-8").splitlines())
    return [match for match in found if match is not None]


@contextlib.contextmanager
def bare_root():
    """pytest's own handlers off the root for the block, so ``install`` adds
    its console handler (``logs.py``, trap 4), and back on afterwards. Taken
    off inside the test, not in a fixture: pytest adds them again around each
    phase."""
    root = logging.getLogger()
    pytest_handlers = root.handlers[:]
    for handler in pytest_handlers:
        root.removeHandler(handler)
    try:
        yield
    finally:
        for handler in pytest_handlers:
            root.addHandler(handler)


@pytest.mark.parametrize("verbose", [False, True])
def test_the_generate_calls_info_line_reaches_the_console_and_the_file(
    tmp_path, capsys, verbose
):
    """The cost of each generate call is logged at INFO by
    ``sensei_top.ai.llm.client``, and a user is promised it (non-negotiable 5,
    "never silent"): it reaches the console and the file at the default
    levels and under ``--verbose``."""
    with bare_root():
        path = run(tmp_path, *(["--verbose"] if verbose else []), "config")
        capsys.readouterr()
        logging.getLogger(llm_client.__name__).info("the cost line")
        console = capsys.readouterr().err.splitlines()

    assert console == ["INFO the cost line"]
    assert [line["message"] for line in lines(path)[1:]] == ["the cost line"]
