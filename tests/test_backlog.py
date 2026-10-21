"""scripts/check_backlog.py: the register's format and every reference to its items.

The first test runs the script over the tree. The rest build a synthetic
register in tmp_path and point the script at it, so none reads BACKLOG.md.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_backlog.py"

LABEL = "type: fix · priority: P2 · status: needs-data · area: mtgo cli"


def item(n: int, label: str = LABEL) -> str:
    return f"### BL-{n:03d} · A title\n\n{label}\n\n**Why deferred:** x\n\n"


def register(*items: str, next_id: str = "Next ID: BL-010") -> str:
    return f"# Backlog\n\n{next_id}\n\n" + "".join(items)


@pytest.fixture(scope="module")
def backlog():
    spec = importlib.util.spec_from_file_location("check_backlog", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(backlog, tmp_path: Path, text: str, files: dict[str, str] | None = None):
    reg = tmp_path / "BACKLOG.md"
    reg.write_text(text, encoding="utf-8")
    return backlog.collect(reg, files or {})


def kinds(hits) -> list[str]:
    return [h[2] for h in hits]


def test_the_tree_has_a_valid_register_and_no_dangling_reference():
    out = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stdout


def test_a_valid_register_has_no_hit(backlog, tmp_path):
    assert run(backlog, tmp_path, register(item(1), item(2))) == []


def test_a_duplicate_id_hits(backlog, tmp_path):
    hits = run(backlog, tmp_path, register(item(1), item(1)))
    assert kinds(hits) == ["duplicate-id"]


def test_a_malformed_heading_hits(backlog, tmp_path):
    bad = "### BL-12 · Short number\n\n" + LABEL + "\n\n"
    assert "heading" in kinds(run(backlog, tmp_path, register(bad)))
    bad = "### BL-012 - ascii dash\n\n" + LABEL + "\n\n"
    assert "heading" in kinds(run(backlog, tmp_path, register(bad)))


def test_an_unknown_label_value_hits(backlog, tmp_path):
    for label in (
        LABEL.replace("fix", "bug"),
        LABEL.replace("P2", "P9"),
        LABEL.replace("needs-data", "later"),
        LABEL.replace("mtgo cli", "mtgo nowhere"),
        LABEL.replace("type:", "kind:"),
    ):
        assert kinds(run(backlog, tmp_path, register(item(1, label)))) == ["label"], label


def test_an_incomplete_label_line_hits(backlog, tmp_path):
    short = "type: fix · priority: P2 · status: ready"
    hits = run(backlog, tmp_path, register(item(1, short)))
    assert kinds(hits) == ["label"] and "missing area" in hits[0][3]


def test_a_missing_label_line_hits(backlog, tmp_path):
    assert kinds(run(backlog, tmp_path, register("### BL-001 · T\n\n**Why deferred:** x\n"))) == [
        "label"
    ]
    assert kinds(run(backlog, tmp_path, register("### BL-001 · T\n"))) == ["label"]


def test_next_id_must_exceed_every_id(backlog, tmp_path):
    assert kinds(run(backlog, tmp_path, register(item(3), next_id="Next ID: BL-003"))) == [
        "next-id"
    ]
    assert kinds(run(backlog, tmp_path, register(item(3), next_id="Next ID: BL-004"))) == []
    assert kinds(run(backlog, tmp_path, register(item(3), next_id="no id here"))) == ["next-id"]


def test_a_dangling_reference_in_a_tracked_file_hits(backlog, tmp_path):
    files = {"src/a.py": "# see BL-001 and BL-007\n", "docs/x.md": "fine\n"}
    hits = run(backlog, tmp_path, register(item(1)), files)
    assert [(h[0], h[1], h[3]) for h in hits] == [("src/a.py", 1, "BL-007")]


def test_the_changelog_and_the_next_id_line_are_exempt(backlog, tmp_path):
    files = {"CHANGELOG.md": "closed BL-099\n"}
    assert run(backlog, tmp_path, register(item(1)), files) == []


def test_a_reference_in_the_register_itself_is_checked(backlog, tmp_path):
    text = register(item(1) + "Related: BL-005.\n\n")
    assert [h[3] for h in run(backlog, tmp_path, text)] == ["BL-005"]
