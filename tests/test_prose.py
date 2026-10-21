"""scripts/check_prose.py: no plan labels, no line references, AGENTS.md within its ceiling.

The first test is the guard: it runs the script over the tree and fails with
its report. The rest pin each rule on synthetic text, with the tracked-path
set passed in, so none of them reads the tree.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_prose.py"


def test_the_tree_has_no_label_line_reference_or_long_agents():
    out = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stdout


@pytest.fixture(scope="module")
def prose():
    spec = importlib.util.spec_from_file_location("check_prose", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_label_in_a_python_comment_or_docstring_hits(prose):
    src = '"""Module for plan 12."""\n\ndef f():\n    # see brief §3\n    """Phase 4 only."""\n'
    hits = prose.label_hits(prose.python_prose(src))
    assert hits == [(1, "plan 12"), (4, "brief §"), (5, "Phase 4")]


def test_the_same_words_in_a_string_literal_do_not(prose):
    src = 'MSG = "plan 12 is done"\nprint("phase 3")\nx = f("brief §1")\n'
    assert prose.label_hits(prose.python_prose(src)) == []


def test_a_bare_section_sign_is_not_a_label(prose):
    assert prose.label_hits(prose.python_prose("# §1.2 is a key of LINES\n")) == []


def test_a_label_in_a_ts_comment_hits_and_one_in_a_string_does_not(prose):
    src = 'const a = "phase 3"; // plan 7\n/* brief §2\n   x */\nconst u = "http://x/plan 9";\n'
    assert prose.label_hits(prose.ts_prose(src)) == [(1, "plan 7"), (2, "brief §")]


TRACKED = {"src/sensei_top/live.py", "scripts/check_doc_refs.py", "a/config.py", "b/config.py"}


def test_a_line_reference_to_a_tracked_file_hits(prose):
    text = "see live.py:589 and src/sensei_top/live.py:12\nand scripts/check_doc_refs.py:3"
    assert [h for h in prose.line_ref_hits(text, TRACKED)] == [
        (1, "live.py:589"),
        (1, "src/sensei_top/live.py:12"),
        (2, "scripts/check_doc_refs.py:3"),
    ]


def test_a_bare_name_two_tracked_files_share_does_not_hit(prose):
    assert prose.line_ref_hits("config.py:21 but a/config.py:3", TRACKED) == [(1, "a/config.py:3")]


def test_a_line_reference_to_an_untracked_or_third_party_file_does_not(prose):
    text = "sensei_top/m.py:2 and util/steam/config.py:216"
    assert prose.line_ref_hits(text, TRACKED) == []


def test_agents_over_its_ceiling_hits(prose):
    assert prose.agents_hit(prose.AGENTS_MAX_LINES) is None
    assert prose.agents_hit(prose.AGENTS_MAX_LINES + 1)
