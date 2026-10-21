"""scripts/check_doc_refs.py: the names the docs give still exist in the tree.

The first test is the guard: it runs the script over every doc and fails
with its report, so a rename that leaves a doc behind is caught here rather
than by the next reader. The rest pin what the script counts as a name,
against this repository's own tree, which is the only tree it ever reads.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_doc_refs.py"


def test_every_name_the_docs_give_exists():
    out = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stdout


@pytest.fixture(scope="module")
def refs():
    spec = importlib.util.spec_from_file_location("check_doc_refs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, module.Tree()


@pytest.mark.parametrize(
    "span",
    [
        "web/src/shell/Rail.tsx",
        "shell/Rail.tsx",
        "src/sensei_top/migrations/NNN_*.sql",
        "cli.py::_require_loopback",
        "guide/play.key_card_timing",
        "GET /api/current-match/read",
        "--watch",
        "key_card_timing",
        "data/sensei-top.db",
    ],
)
def test_a_name_the_tree_has_passes(refs, span):
    module, tree = refs
    assert module.check(span, tree) == []


@pytest.mark.parametrize(
    ("span", "miss"),
    [
        ("shell/Nowhere.tsx", ("path", "shell/Nowhere.tsx")),
        ("cli.py::_no_such_helper", ("symbol", "cli.py::_no_such_helper")),
        ("/api/no-such-route", ("route", "/api/no-such-route")),
        ("--no-such-flag", ("flag", "--no-such-flag")),
        ("no_such_analyzer", ("name", "no_such_analyzer")),
        ("NoSuchCard", ("name", "NoSuchCard")),
    ],
)
def test_a_name_the_tree_lacks_is_reported(refs, span, miss):
    module, tree = refs
    assert module.check(span, tree) == [miss]


@pytest.mark.parametrize(
    "span",
    # a branch, another program's file, a GitHub repository, an English word
    ["feature/<topic>", "Player.log", "owner/repository", "comfortable"],
)
def test_what_is_not_a_name_of_this_tree_is_not_checked(refs, span):
    module, tree = refs
    assert module.check(span, tree) == []


def misses_in(module, tree, path, body):
    """The (kind, name) of each stale span in one file's comments and docstrings."""
    tree.prose[path] = body
    try:
        return [(k, n) for f, _, k, n in module.prose_misses(tree) if f == path]
    finally:
        del tree.prose[path]


def test_a_comment_naming_a_real_symbol_passes(refs):
    module, tree = refs
    assert misses_in(module, tree, "src/x.py", "# see `cli.py::_require_loopback`\n") == []


def test_a_comment_naming_a_missing_symbol_or_path_is_reported(refs):
    module, tree = refs
    body = '"""Docs: ``cli.py::no_such_function``, `shell/Nowhere.tsx`, `/api/no-such-route`."""\n'
    assert misses_in(module, tree, "src/x.py", body) == [
        ("symbol", "cli.py::no_such_function"),
        ("path", "shell/Nowhere.tsx"),
        ("route", "/api/no-such-route"),
    ]


def test_a_bare_name_in_a_comment_is_not_checked(refs):
    module, tree = refs
    body = "# calls `model_validate` and `NoSuchCard`\n"
    assert misses_in(module, tree, "src/x.py", body) == []


def test_a_string_literal_is_not_prose(refs):
    module, tree = refs
    assert misses_in(module, tree, "src/x.py", 'x = "`shell/Nowhere.tsx`"\n') == []


def test_a_typescript_comment_is_read(refs):
    module, tree = refs
    body = "const a = '// `shell/Nope.tsx`'\n// `shell/Nowhere.tsx`\n/* `cli.py::nope_fn` */\n"
    assert misses_in(module, tree, "web/src/x.ts", body) == [
        ("path", "shell/Nowhere.tsx"),
        ("symbol", "cli.py::nope_fn"),
    ]


def test_a_symbol_only_a_comment_of_its_own_file_names_is_missing(refs):
    # the self-satisfaction case: the docstring's mention must not make the symbol exist
    module, tree = refs
    body = '"""``later.py::only_in_this_docstring``"""\n'
    tree.text["src/later.py"] = module.code_only("src/later.py", body)
    try:
        assert not tree.symbol("later.py", "only_in_this_docstring")
    finally:
        del tree.text["src/later.py"]


def test_what_is_not_a_reference_is_not_a_miss(refs):
    module, tree = refs
    body = "# the ``::1`` host, ``[::1]:8000``, ``http://[::1`` and ``…/SomeMessage``\n"
    assert misses_in(module, tree, "src/x.py", body) == []
