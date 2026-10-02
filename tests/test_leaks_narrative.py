"""Tests for review/leaks_narrative.py — the training-plan prompt built over
the leak finder's ranked output. The module itself no longer makes the call
(that moved to ``sensei_top.llm`` — see ``tests/test_llm.py`` for the
credential-gating and fake-completion coverage), so there is nothing here to
fake an SDK response for.
"""

from __future__ import annotations

from sensei_top.review import leaks_narrative
from sensei_top.review.leaks import Leak


def _leak(**overrides) -> Leak:
    base = dict(
        code="mana_screwed", category="deckbuilding", sample_title="Stuck on lands",
        n_with=15, win_rate_with=0.3, ci_with=(0.15, 0.5),
        n_without=40, win_rate_without=0.55, ci_without=(0.4, 0.7),
        gap=0.25, match_ids_with=("m1", "m2"),
    )
    base.update(overrides)
    return Leak(**base)


def test_build_leaks_context_is_none_for_an_empty_list():
    assert leaks_narrative.build_leaks_context([]) is None


def test_build_leaks_context_lists_each_pattern_with_its_interval():
    context = leaks_narrative.build_leaks_context([_leak()])
    assert "Stuck on lands" in context
    assert "mana_screwed" in context
    assert "30%" in context and "15-50%" in context
    assert "55%" in context and "40-70%" in context


def test_full_prompt_puts_the_framing_above_the_evidence():
    text = leaks_narrative.full_prompt("EVIDENCE-BODY")
    assert leaks_narrative.SYSTEM_PROMPT in text
    assert "EVIDENCE-BODY" in text
    assert text.index(leaks_narrative.SYSTEM_PROMPT) < text.index("EVIDENCE-BODY")


def test_leaks_context_carries_no_local_paths():
    """Same guard test_narrative.py's carries for the match report — a
    filesystem path would reveal the machine, and this text can really
    leave it now that a credential can be configured."""
    context = leaks_narrative.build_leaks_context([_leak()])
    lowered = context.lower()
    for leaked in ("/home/", "c:\\users", "/users/", "appdata"):
        assert leaked not in lowered
