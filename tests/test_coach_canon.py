"""Tests for coach/canon.py: the reading list's own shape, and that its
``topics`` name things that actually exist elsewhere in this codebase
(a real ``Finding.code``, or one of this module's own tags) rather than a
code an analyzer no longer emits.

Every "what does the codebase actually say" check here reads the source of
``review/`` at test time instead of hardcoding a copy of it, so a rename in
an analyzer or in ``leaks.py`` fails this test rather than silently going
stale alongside it.
"""

from __future__ import annotations

import re
from pathlib import Path

import sensei_top.review as review_pkg
from sensei_top.coach.canon import (
    ALLOWED_DOMAINS,
    BROAD_TAGS,
    CANON,
    CORE_IDS,
    LEAK_CODES,
    entries_for,
)

REVIEW_DIR = Path(review_pkg.__file__).parent
_CODE_KWARG_RE = re.compile(r'code="([a-zA-Z_][a-zA-Z0-9_]*)"')
# review/analyzers/baseline.py emits several Finding codes positionally —
# `Finding("play_draw_split", ANALYZER, ...)` — rather than via `code=`, so
# the keyword-only scan above misses them. A Finding's first positional
# argument is exactly as real a code as a keyword one.
_CODE_POSITIONAL_RE = re.compile(r'Finding\(\s*"([a-zA-Z_][a-zA-Z0-9_]*)"')
_MANA_LEAK_TUPLE_RE = re.compile(r'\("(mana_\w+)",\s*(?:\w+,\s*)+"[^"]+"\)')


def _real_finding_codes() -> set[str]:
    """Every ``Finding.code`` an analyzer actually emits, keyword or
    positional, scanned from ``review/`` itself. See ``findings.py``'s own
    docstring: ``Finding.code`` is a stable identifier, not prose, and a
    rollup (the leak finder, and now the coach) groups on it — a rename
    here is exactly the kind of change this test exists to catch."""
    codes: set[str] = set()
    for path in REVIEW_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        codes.update(_CODE_KWARG_RE.findall(text))
        codes.update(_CODE_POSITIONAL_RE.findall(text))
    return codes


def _real_leak_codes() -> set[str]:
    """The two synthetic codes ``review/leaks.py::_mana_leaks`` emits for
    screw/flood — read from its own code/ids/known_ids/label tuple, not
    copied. The regex tolerates any number of bareword fields between the
    code and the label string, since that tuple's own arity is an
    implementation detail (it grew a ``known_ids`` element to track screw
    and flood's known populations separately) — not the invariant this test
    checks, which is only the two literal code strings."""
    text = (REVIEW_DIR / "leaks.py").read_text(encoding="utf-8")
    return set(_MANA_LEAK_TUPLE_RE.findall(text))


def test_ids_are_1_through_len_in_order_and_label_is_r_prefixed():
    assert [entry.id for entry in CANON] == list(range(1, len(CANON) + 1))
    for entry in CANON:
        assert entry.label == f"R{entry.id}"


def test_urls_start_with_https_and_are_unique():
    urls = [entry.url for entry in CANON]
    assert all(url.startswith("https://") for url in urls)
    assert len(set(urls)) == len(urls)


def test_author_title_summary_are_non_empty():
    for entry in CANON:
        assert entry.author.strip()
        assert entry.title.strip()
        assert entry.summary.strip()


def test_summary_is_in_our_own_words_never_a_pasted_quote():
    for entry in CANON:
        assert '"' not in entry.summary


def test_the_scan_catches_baseline_pys_positional_finding_codes():
    """``review/analyzers/baseline.py`` writes ``Finding("play_draw_split",
    ANALYZER, ...)`` positionally rather than as ``code="play_draw_split"``.
    Pinning that one code here means a regression in the positional half of
    ``_real_finding_codes`` fails on its own, even on a run where no canon
    topic happens to name a ``baseline.py`` code."""
    assert "play_draw_split" in _real_finding_codes()


def test_every_topic_is_a_real_finding_code_or_a_declared_tag():
    allowed = _real_finding_codes() | LEAK_CODES | BROAD_TAGS
    for entry in CANON:
        for topic in entry.topics:
            assert topic in allowed, (
                f"R{entry.id} ({entry.title!r}) names topic {topic!r}, which is "
                f"neither a Finding.code in review/ nor in LEAK_CODES | BROAD_TAGS"
            )


def test_leak_codes_matches_what_leaks_py_actually_emits_for_screw_flood():
    assert _real_leak_codes() == LEAK_CODES


def test_every_core_id_exists():
    ids = {entry.id for entry in CANON}
    for core_id in CORE_IDS:
        assert core_id in ids


def test_entries_for_with_nothing_wanted_returns_exactly_the_core_entries():
    result = entries_for(set(), set())
    assert [entry.id for entry in result] == sorted(CORE_IDS)


def test_entries_for_a_finding_code_adds_the_matching_entry_to_the_core():
    sweepers = next(entry for entry in CANON if entry.title == "Board Sweepers")
    result = entries_for({"over_committed_into_sweeper"}, set())
    expected_ids = sorted(set(CORE_IDS) | {sweepers.id})
    assert [entry.id for entry in result] == expected_ids


def test_entries_for_a_broad_tag_returns_every_carrier_plus_core():
    tag = "sideboarding"
    assert tag in BROAD_TAGS
    carriers = {entry.id for entry in CANON if tag in entry.topics}
    result = entries_for(set(), {tag})
    assert [entry.id for entry in result] == sorted(carriers | set(CORE_IDS))


def test_allowed_domains_are_non_empty_unique_bare_lowercase_hostnames():
    assert len(ALLOWED_DOMAINS) > 0
    assert len(set(ALLOWED_DOMAINS)) == len(ALLOWED_DOMAINS)
    for domain in ALLOWED_DOMAINS:
        assert domain == domain.lower()
        assert "://" not in domain
        assert "/" not in domain
        assert not domain.startswith("www.")
