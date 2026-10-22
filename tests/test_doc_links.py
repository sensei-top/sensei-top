"""scripts/check_doc_links.py: every `docs/<name>.md, "<Section>"` still resolves.

The first test is the guard, as in test_doc_refs.py: it runs the script over
the tree and fails with its report. The rest pin `title_ok`'s rule against a
made-up doc, so a section reference has to name a heading whole.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_doc_links.py"


def test_every_doc_reference_resolves():
    out = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stdout


@pytest.fixture(scope="module")
def links():
    spec = importlib.util.spec_from_file_location("check_doc_links", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _doc(links, text: str, headings: list[str]):
    return (links.norm(text), [links.norm(h) for h in headings], set())


def test_a_section_reference_names_the_whole_heading(links):
    doc = _doc(links, "", ["The event rule (`table/queues.py`)"])
    every = {links.norm("The event rule (`table/queues.py`)")}
    assert links.title_ok("The event rule (`table/queues.py`)", doc, every)
    assert not links.title_ok("The event rule", doc, every)


def test_a_heading_in_another_doc_does_not_resolve(links):
    doc = _doc(links, "", ["Ports"])
    assert not links.title_ok("Shared primitives", doc, {"ports", "shared primitives"})


def test_a_title_that_is_no_heading_falls_back_to_the_text(links):
    doc = _doc(links, "Use one hue for nominal categories.", ["Palette"])
    assert links.title_ok("one hue for nominal categories", doc, {"palette"})
    assert not links.title_ok("two hues", doc, {"palette"})
