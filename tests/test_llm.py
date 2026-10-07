"""Tests for src/sensei_top/llm/ — the opt-in Claude call AGENTS.md
non-negotiable #5 now permits — and for the three ``POST .../narrative``
routes it feeds.

No test here ever makes a network call: ``llm/config.py`` is exercised
against real env vars and a scratch config file (never a real key),
``llm/client.py`` against a fake ``anthropic.Anthropic`` that never opens a
socket, and the API routes against monkeypatched ``llm_config.load`` /
``llm_client.write_prose`` / ``llm_client.write_json``.
``test_no_credential_means_no_client_is_constructed`` is the one that pins
the actual guarantee: with nothing configured, none of the three routes may
even try to build a client.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from sensei_top import cli as cli_module
from sensei_top.api import create_app
from sensei_top.api.routes import matches as matches_routes
from sensei_top.api.routes import review as review_routes
from sensei_top.db import open_database
from sensei_top.llm import client as llm_client_module
from sensei_top.llm import config as llm_config_module
from sensei_top.llm.client import (
    REPORT_MODELS,
    Citation,
    Completion,
    LLMError,
    price_per_mtok,
    strict_schema,
    write_json,
    write_prose,
    write_report,
)
from sensei_top.llm.config import LLMConfig, load
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.review.narrative_store import context_hash

FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"


# --- llm/config.py: credential resolution -------------------------------


def _write_config(
    tmp_path: Path, *, api_key: str, model: str | None = None, effort: str | None = None
):
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir(exist_ok=True)
    lines = ["[claude]", f'api_key = "{api_key}"']
    if model:
        lines.append(f'model = "{model}"')
    if effort:
        lines.append(f'effort = "{effort}"')
    (config_dir / "config.toml").write_text("\n".join(lines) + "\n")


def test_nothing_configured_yields_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


def test_env_key_wins_but_the_file_still_supplies_model_and_effort(monkeypatch, tmp_path):
    _write_config(tmp_path, api_key="file-key", model="claude-sonnet-5", effort="low")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")

    cfg = load()
    assert cfg == LLMConfig(api_key="env-key", model="claude-sonnet-5", effort="low")


def test_env_key_alone_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    cfg = load()
    assert cfg == LLMConfig(api_key="env-key", model="claude-opus-5", effort="high")


def test_the_config_file_alone_is_enough(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_config(tmp_path, api_key="file-key", model="claude-sonnet-5", effort="medium")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() == LLMConfig(api_key="file-key", model="claude-sonnet-5", effort="medium")


def test_malformed_toml_yields_none_not_an_exception(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("this is not { valid toml at all")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


def test_a_file_with_no_claude_table_yields_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[other]\nfoo = "bar"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


def test_a_missing_file_yields_none(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert load() is None


# --- llm/client.py: a fake anthropic.Anthropic, never a socket ----------


class _FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_final_message(self):
        return self._message


class _FakeMessages:
    """``messages=`` is a queue consumed one per ``.stream()`` call, for
    tests that drive a ``pause_turn`` loop through more than one request;
    a plain ``message=`` (the original shape) is returned unchanged on
    every call, as every pre-existing test here still expects.
    ``captures=`` records every call's kwargs, in order, for tests that
    need to see more than the last one (``capture=`` still records only
    the most recent, for every existing single-call test)."""

    def __init__(self, message=None, *, messages=None, error=None, capture=None, captures=None):
        self._message = message
        self._queue = list(messages) if messages is not None else None
        self._error = error
        self._capture = capture
        self._captures = captures

    def stream(self, **kwargs):
        # write_report reuses and mutates one ``messages`` list across
        # iterations of its pause_turn loop (appending the paused turn back
        # in-place) -- snapshot it here so a capture reflects what was sent
        # *at this call*, not what the list looks like after later calls.
        snapshot = dict(kwargs)
        if "messages" in snapshot:
            snapshot["messages"] = list(snapshot["messages"])
        if self._capture is not None:
            self._capture.clear()
            self._capture.update(snapshot)
        if self._captures is not None:
            self._captures.append(snapshot)
        if self._error is not None:
            raise self._error
        message = self._queue.pop(0) if self._queue is not None else self._message
        return _FakeStream(message)


class _FakeAnthropic:
    def __init__(self, message=None, *, messages=None, error=None, capture=None, captures=None):
        self.messages = _FakeMessages(
            message, messages=messages, error=error, capture=capture, captures=captures
        )


def _fake_message(
    *, text="Focus on curving out.", model="claude-opus-5",
    input_tokens=100, output_tokens=50, stop_reason="end_turn", stop_details=None,
    citations=None, content_blocks=None, web_search_requests=None,
):
    """``content_blocks`` overrides the single default text block entirely,
    for tests that need a ``web_search_tool_result`` block or more than one
    ``text`` block. ``web_search_requests`` populates
    ``usage.server_tool_use`` (``None`` when omitted, matching a real
    response that never called a server tool — ``Usage.server_tool_use`` is
    ``Optional`` in the SDK's own type)."""
    if content_blocks is None:
        content_blocks = (
            [SimpleNamespace(type="text", text=text, citations=citations)] if text else []
        )
    return SimpleNamespace(
        content=content_blocks,
        model=model,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            server_tool_use=(
                SimpleNamespace(web_search_requests=web_search_requests)
                if web_search_requests is not None
                else None
            ),
        ),
        stop_reason=stop_reason,
        stop_details=stop_details,
    )


def _patch_client(monkeypatch, **kwargs) -> _FakeAnthropic:
    fake = _FakeAnthropic(**kwargs)
    monkeypatch.setattr(llm_client_module.anthropic, "Anthropic", lambda **_: fake)
    return fake


def test_write_prose_returns_the_completions_fields(monkeypatch):
    _patch_client(
        monkeypatch, message=_fake_message(text="Nice game.", input_tokens=200, output_tokens=80)
    )
    result = write_prose("prompt text", cfg=LLMConfig(api_key="k"), label="test")
    assert result.text == "Nice game."
    assert result.model == "claude-opus-5"
    assert result.input_tokens == 200
    assert result.output_tokens == 80


def test_cost_is_measured_from_usage_for_a_priced_model(monkeypatch):
    _patch_client(
        monkeypatch,
        message=_fake_message(
            model="claude-opus-5", input_tokens=1_000_000, output_tokens=1_000_000
        ),
    )
    result = write_prose("p", cfg=LLMConfig(api_key="k"), label="test")
    assert result.cost_usd == pytest.approx(5.00 + 25.00)


def test_an_unpriced_model_costs_none_not_a_guess(monkeypatch):
    """AGENTS.md non-negotiable #4 applies to money the same as it applies
    to match data: an unrecognized model must not invent a price — NULL
    over a guess, so ``None`` rather than a fabricated ``0.0``."""
    _patch_client(
        monkeypatch,
        message=_fake_message(
            model="some-future-model", input_tokens=1_000_000, output_tokens=1_000_000
        ),
    )
    result = write_prose("p", cfg=LLMConfig(api_key="k"), label="test")
    assert result.cost_usd is None


# --- REPORT_MODELS: the coach tab's model dropdown ------------------------


def test_report_models_are_all_priced_and_get_dynamic_filtering():
    for model in REPORT_MODELS:
        assert model in llm_client_module._PRICES
        assert model in llm_client_module._DYNAMIC_FILTERING_MODELS


def test_haiku_is_priced_but_not_offered_in_report_models():
    assert "claude-haiku-4-5" in llm_client_module._PRICES
    assert "claude-haiku-4-5" not in REPORT_MODELS


def test_opus_5_5_cost_is_4_and_20_per_mtok():
    # $4/$20 per MTok, not read off a live call -- 1M in + 1M out = $4 + $20.
    cost = llm_client_module._cost("claude-opus-5-5", 1_000_000, 1_000_000)
    assert cost == pytest.approx(24.0)


def test_price_per_mtok_returns_the_priced_tuple():
    assert price_per_mtok("claude-opus-5-5") == (4.00, 20.00)


def test_price_per_mtok_returns_none_for_an_unpriced_model():
    assert price_per_mtok("some-future-model") is None


def test_a_refusal_raises_llm_error_with_the_category(monkeypatch):
    _patch_client(
        monkeypatch,
        message=_fake_message(
            text="", stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")
        ),
    )
    with pytest.raises(LLMError, match="cyber"):
        write_prose("p", cfg=LLMConfig(api_key="k"), label="test")


def test_write_json_requests_adaptive_thinking_and_structured_output(monkeypatch):
    capture: dict = {}
    _patch_client(monkeypatch, message=_fake_message(text='{"a": 1}'), capture=capture)
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    write_json("p", schema, cfg=LLMConfig(api_key="k"), label="test")
    assert capture["thinking"] == {"type": "adaptive"}
    assert capture["output_config"]["format"] == {"type": "json_schema", "schema": schema}
    # Opus 5 rejects budget_tokens with a 400 -- must never be sent.
    assert "budget_tokens" not in capture["thinking"]


def test_auth_error_maps_to_a_clean_llm_error(monkeypatch):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.AuthenticationError(
        "bad key", response=httpx2.Response(401, request=request), body=None
    )
    _patch_client(monkeypatch, error=error)
    with pytest.raises(LLMError, match="rejected"):
        write_prose("p", cfg=LLMConfig(api_key="k"), label="test")


def test_rate_limit_error_maps_to_a_clean_llm_error(monkeypatch):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=request), body=None
    )
    _patch_client(monkeypatch, error=error)
    with pytest.raises(LLMError, match="rate limit"):
        write_prose("p", cfg=LLMConfig(api_key="k"), label="test")


def test_connection_error_maps_to_a_clean_llm_error(monkeypatch):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(message="conn fail", request=request)
    _patch_client(monkeypatch, error=error)
    with pytest.raises(LLMError, match="Could not reach"):
        write_prose("p", cfg=LLMConfig(api_key="k"), label="test")


# --- write_report: the coach's web-search entry point --------------------


def _citation(url, title, cited_text):
    return SimpleNamespace(
        type="web_search_result_location", url=url, title=title, cited_text=cited_text
    )


def test_write_report_sends_no_tools_when_web_search_is_off(monkeypatch):
    capture: dict = {}
    _patch_client(monkeypatch, message=_fake_message(), capture=capture)
    write_report(
        "p", cfg=LLMConfig(api_key="k", web_search=False), label="coach",
        allowed_domains=["mtggoldfish.com"],
    )
    assert "tools" not in capture


@pytest.mark.parametrize(
    "model, expected_type",
    [
        ("claude-opus-5", "web_search_20260209"),
        ("claude-opus-5-5", "web_search_20260209"),
        ("claude-fable-5-1", "web_search_20260209"),
        ("claude-sonnet-5", "web_search_20260209"),
        ("claude-haiku-4-5", "web_search_20250305"),
        ("some-future-model", "web_search_20250305"),
    ],
)
def test_write_report_picks_the_tool_version_by_model(monkeypatch, model, expected_type):
    """The 4.6-and-later models get the dynamic-filtering tool; an older or
    unrecognized model gets the basic one."""
    capture: dict = {}
    _patch_client(monkeypatch, message=_fake_message(model=model), capture=capture)
    write_report(
        "p", cfg=LLMConfig(api_key="k", model=model), label="coach",
        allowed_domains=["mtggoldfish.com", "starcitygames.com"],
    )
    tool = capture["tools"][0]
    assert tool["type"] == expected_type
    assert tool["name"] == "web_search"
    assert tool["max_uses"] == 8
    assert tool["allowed_domains"] == ["mtggoldfish.com", "starcitygames.com"]


def test_write_report_sums_usage_across_a_pause_turn_loop(monkeypatch):
    first = _fake_message(
        text="Partial analysis. ", stop_reason="pause_turn",
        input_tokens=1000, output_tokens=500, web_search_requests=2,
    )
    second = _fake_message(
        text="Final analysis.", stop_reason="end_turn",
        input_tokens=300, output_tokens=150, web_search_requests=1,
    )
    _patch_client(monkeypatch, messages=[first, second])

    result = write_report(
        "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
    )
    assert result.text == "Partial analysis. Final analysis."
    assert result.input_tokens == 1300
    assert result.output_tokens == 650
    assert result.web_search_requests == 3


def test_write_report_resends_the_paused_content_unchanged(monkeypatch):
    first = _fake_message(text="Partial. ", stop_reason="pause_turn")
    second = _fake_message(text="Done.", stop_reason="end_turn")
    captures: list[dict] = []
    _patch_client(monkeypatch, messages=[first, second], captures=captures)

    write_report(
        "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
    )

    assert len(captures) == 2
    assert captures[0]["messages"] == [{"role": "user", "content": "p"}]
    assert captures[1]["messages"] == [
        {"role": "user", "content": "p"},
        {"role": "assistant", "content": first.content},
    ]


def test_write_report_caps_pause_turn_continuations_at_three(monkeypatch):
    paused = [
        _fake_message(
            text=f"Part {i}. ", stop_reason="pause_turn", input_tokens=10, output_tokens=10
        )
        for i in range(5)
    ]
    captures: list[dict] = []
    _patch_client(monkeypatch, messages=paused, captures=captures)

    result = write_report(
        "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
    )
    # One initial request plus at most 3 continuations -- 4 total, never 5.
    assert len(captures) == 4
    assert result.text == "Part 0. Part 1. Part 2. Part 3. "


def test_write_report_dedupes_citations_by_url(monkeypatch):
    block1 = SimpleNamespace(
        type="text", text="First. ",
        citations=[_citation("https://mtggoldfish.com/a", "Article A", "quote 1")],
    )
    block2 = SimpleNamespace(
        type="text", text="Second.",
        citations=[
            _citation("https://mtggoldfish.com/a", "Article A", "quote 2"),
            _citation("https://mtggoldfish.com/b", "Article B", "quote 3"),
        ],
    )
    _patch_client(monkeypatch, message=_fake_message(content_blocks=[block1, block2]))

    result = write_report(
        "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
    )
    assert result.citations == (
        Citation(url="https://mtggoldfish.com/a", title="Article A", cited_text="quote 1"),
        Citation(url="https://mtggoldfish.com/b", title="Article B", cited_text="quote 3"),
    )


def test_write_report_logs_content_block_type_counts_and_citation_coverage(monkeypatch, caplog):
    """1c's diagnostic: a ``Counter`` of every block type seen across the
    whole loop, plus how many text blocks carried a non-empty ``citations``
    list -- the fact-finding line for docs/coach.md's "no web citations are
    stored" gap. One text block cited, one uncited, plus a
    ``web_search_tool_result`` block, across a two-request pause_turn loop
    so the counts also prove they accumulate rather than reset per call."""
    cited_block = SimpleNamespace(
        type="text", text="Cited. ",
        citations=[_citation("https://mtggoldfish.com/a", "Article A", "quote")],
    )
    search_result_block = SimpleNamespace(
        type="web_search_tool_result", tool_use_id="srvtoolu_1",
        content=SimpleNamespace(type="web_search_tool_result", content=[]),
    )
    first = SimpleNamespace(
        content=[cited_block, search_result_block],
        model="claude-opus-5",
        usage=SimpleNamespace(
            input_tokens=100, output_tokens=50,
            server_tool_use=SimpleNamespace(web_search_requests=1),
        ),
        stop_reason="pause_turn",
        stop_details=None,
    )
    uncited_block = SimpleNamespace(type="text", text="Uncited.", citations=None)
    second = _fake_message(content_blocks=[uncited_block], stop_reason="end_turn")
    _patch_client(monkeypatch, messages=[first, second])

    with caplog.at_level("INFO"):
        write_report(
            "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
        )

    lines = [m for m in caplog.messages if "content blocks" in m]
    assert len(lines) == 1
    assert "'text': 2" in lines[0]
    assert "'web_search_tool_result': 1" in lines[0]
    assert "1/2 text blocks carried citations" in lines[0]


def test_write_report_logs_and_continues_on_a_search_error_block(monkeypatch, caplog):
    error_block = SimpleNamespace(
        type="web_search_tool_result",
        tool_use_id="srvtoolu_1",
        content=SimpleNamespace(type="web_search_tool_result_error", error_code="unavailable"),
    )
    text_block = SimpleNamespace(type="text", text="Still wrote something.", citations=None)
    _patch_client(monkeypatch, message=_fake_message(content_blocks=[error_block, text_block]))

    with caplog.at_level("WARNING"):
        result = write_report(
            "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
        )
    assert result.text == "Still wrote something."
    assert any("unavailable" in message for message in caplog.messages)


def test_write_report_cost_includes_search_requests(monkeypatch):
    _patch_client(
        monkeypatch,
        message=_fake_message(
            model="claude-opus-5", input_tokens=1_000_000, output_tokens=1_000_000,
            web_search_requests=8,
        ),
    )
    result = write_report(
        "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
    )
    assert result.cost_usd == pytest.approx(5.00 + 25.00 + 8 * 10 / 1000)


def test_write_report_unpriced_model_costs_none(monkeypatch):
    _patch_client(
        monkeypatch,
        message=_fake_message(model="some-future-model", web_search_requests=3),
    )
    result = write_report(
        "p", cfg=LLMConfig(api_key="k", model="some-future-model"), label="coach",
        allowed_domains=["mtggoldfish.com"],
    )
    assert result.cost_usd is None


def test_write_report_never_sets_output_config_format(monkeypatch):
    capture: dict = {}
    _patch_client(monkeypatch, message=_fake_message(), capture=capture)
    write_report(
        "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
    )
    assert "format" not in capture["output_config"]


def test_web_search_disabled_400_gives_a_config_hint(monkeypatch):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.BadRequestError(
        "web search is not enabled for this organization",
        response=httpx2.Response(400, request=request), body=None,
    )
    _patch_client(monkeypatch, error=error)
    with pytest.raises(LLMError, match="coach-web-search off"):
        write_report(
            "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
        )


def test_write_report_refusal_still_raises_llm_error(monkeypatch):
    _patch_client(
        monkeypatch,
        message=_fake_message(
            text="", stop_reason="refusal", stop_details=SimpleNamespace(category="cyber")
        ),
    )
    with pytest.raises(LLMError, match="cyber"):
        write_report(
            "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
        )


# --- llm/config.py: load_coach() ------------------------------------------


def test_load_coach_applies_overrides_while_load_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[claude]\n"
        'api_key = "file-key"\n'
        'model = "claude-opus-5"\n'
        'effort = "high"\n'
        "\n"
        "[claude.coach]\n"
        'model = "claude-fable-5-1"\n'
        'effort = "max"\n'
        "web_search = false\n"
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    base = llm_config_module.load()
    assert base == LLMConfig(api_key="file-key", model="claude-opus-5", effort="high")
    assert base.web_search is True

    coach = llm_config_module.load_coach()
    assert coach == LLMConfig(
        api_key="file-key", model="claude-fable-5-1", effort="max", web_search=False
    )

    # load() itself must come back unchanged by the coach table existing.
    assert llm_config_module.load() == base


def test_load_coach_with_no_coach_table_falls_back_to_the_base_config(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_config(tmp_path, api_key="file-key", model="claude-sonnet-5", effort="low")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert llm_config_module.load_coach() == LLMConfig(
        api_key="file-key", model="claude-sonnet-5", effort="low"
    )


def test_load_coach_returns_none_with_no_credential_and_builds_no_client(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def _boom(**_):
        raise AssertionError("anthropic.Anthropic constructed with no credential")

    monkeypatch.setattr(llm_client_module.anthropic, "Anthropic", _boom)
    assert llm_config_module.load_coach() is None


# --- cli.py: the config subcommand's [claude.coach] table -----------------


def test_write_llm_config_round_trips_the_coach_table_and_preserves_other_keys(
    monkeypatch, tmp_path
):
    """Topdeck key written first, coach overrides second -- the order that
    already worked before ``_write_topdeck_config`` was fixed to round-trip
    a nested sub-table, since it never touched ``[claude.coach]`` here."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)
    cli_module._write_topdeck_config(api_key="topdeck-key")
    cli_module._write_llm_config(
        api_key=None, model=None, effort=None,
        coach_model="claude-fable-5-1", coach_effort="max", coach_web_search=False,
    )

    cfg = llm_config_module.load()
    assert cfg.api_key == "base-key"
    assert cfg.model == "claude-opus-5"
    assert cfg.effort == "high"

    coach = llm_config_module.load_coach()
    assert coach.model == "claude-fable-5-1"
    assert coach.effort == "max"
    assert coach.web_search is False

    from sensei_top.metagame import config as topdeck_config_module

    assert topdeck_config_module.load().api_key == "topdeck-key"

    # A later plain --set-effort write must not disturb the coach table or
    # the topdeck table -- they are separate tables, merged not replaced.
    cli_module._write_llm_config(api_key=None, model=None, effort="low")
    assert llm_config_module.load().effort == "low"
    coach_again = llm_config_module.load_coach()
    assert coach_again.model == "claude-fable-5-1"
    assert coach_again.effort == "max"
    assert coach_again.web_search is False
    assert topdeck_config_module.load().api_key == "topdeck-key"


def test_write_topdeck_config_after_coach_overrides_preserves_the_coach_table(
    monkeypatch, tmp_path
):
    """Coach overrides written first, topdeck key second -- this used to
    corrupt ``[claude.coach]`` into a stringified dict, because
    ``_write_topdeck_config`` reads and rewrites every table through
    ``_read_config_tables``/``_write_config_tables``, and those two used to
    flatten every value to a string, unable to represent a nested sub-table
    or a real boolean. Both helpers now round-trip one level of nesting and
    booleans, so this order is safe too."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.metagame import config as topdeck_config_module

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)
    cli_module._write_llm_config(
        api_key=None, model=None, effort=None,
        coach_model="claude-fable-5-1", coach_effort="max", coach_web_search=False,
    )
    cli_module._write_topdeck_config(api_key="topdeck-key")

    coach = llm_config_module.load_coach()
    assert coach.model == "claude-fable-5-1"
    assert coach.effort == "max"
    assert coach.web_search is False
    assert isinstance(coach.web_search, bool)

    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"


def test_write_mtgo_config_preserves_the_claude_and_topdeck_tables(monkeypatch, tmp_path):
    """This is the test that protects a real Anthropic API key: writing the
    MTGO handle must merge into config.toml, never replace it -- and the
    reverse order (mtgo written first, credentials after) must be just as
    safe, mirroring the two coach/topdeck ordering tests above."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.metagame import config as topdeck_config_module
    from sensei_top.mtgo.config import load_handle

    cli_module._write_llm_config(api_key="base-key", model="claude-sonnet-5", effort="low")
    cli_module._write_topdeck_config(api_key="topdeck-key")
    cli_module._write_mtgo_config(handle="Player1")

    cfg = llm_config_module.load()
    assert cfg.api_key == "base-key"
    assert cfg.model == "claude-sonnet-5"
    assert cfg.effort == "low"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "Player1"

    # Reverse order: writing the mtgo handle again after the fact must not
    # disturb either credential table.
    cli_module._write_mtgo_config(handle="otherhandle")
    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "otherhandle"


def test_write_backup_config_preserves_the_claude_topdeck_and_mtgo_tables(monkeypatch, tmp_path):
    """The fourth writer gets the same guarantee as the other three: writing
    backup settings must merge into config.toml, never replace it -- checked
    in both orders, mirroring the mtgo/topdeck ordering tests above."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.backup import config as backup_config_module
    from sensei_top.backup.config import BACKUP_DIR_ENV
    from sensei_top.metagame import config as topdeck_config_module
    from sensei_top.mtgo.config import load_handle

    monkeypatch.delenv(BACKUP_DIR_ENV, raising=False)

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)
    cli_module._write_topdeck_config(api_key="topdeck-key")
    cli_module._write_mtgo_config(handle="Player1")
    cli_module._write_backup_config(directory=str(tmp_path / "some-backups"), keep=3)

    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "Player1"
    backup_cfg = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert backup_cfg.directory == tmp_path / "some-backups"
    assert backup_cfg.keep == 3

    # Reverse order: writing backup settings first must not disturb a
    # credential table written afterwards, any more than the reverse did.
    cli_module._write_backup_config(directory=str(tmp_path / "other-backups"), keep=5)
    cli_module._write_mtgo_config(handle="otherhandle")
    assert llm_config_module.load().api_key == "base-key"
    assert topdeck_config_module.load().api_key == "topdeck-key"
    assert load_handle() == "otherhandle"
    backup_cfg_again = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert backup_cfg_again.directory == tmp_path / "other-backups"
    assert backup_cfg_again.keep == 5


def test_setting_mtgo_dir_alone_does_not_erase_a_configured_handle(monkeypatch, tmp_path):
    """Mirrors test_setting_backup_keep_alone_does_not_erase_a_configured_backup_dir
    just below for mtgo's own two-field table, now that _write_mtgo_config
    merges within its own table too: --set-mtgo-dir run on its own, on a
    later occasion than --set-mtgo-handle, must not blank the handle back to
    unconfigured -- and the reverse must hold too."""
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.mtgo.config import load_handle, resolve_log_dir

    cli_module._write_mtgo_config(handle="Player1")
    cli_module._write_mtgo_config(directory=str(tmp_path / "mtgo-share"))

    assert load_handle() == "Player1"
    directory, source = resolve_log_dir()
    assert directory == tmp_path / "mtgo-share"
    assert source == "config.toml [mtgo] dir"

    # And the reverse: setting the handle again afterwards must not erase
    # the directory set moments ago.
    cli_module._write_mtgo_config(handle="Player2")
    assert load_handle() == "Player2"
    directory_again, _ = resolve_log_dir()
    assert directory_again == tmp_path / "mtgo-share"


def test_setting_backup_keep_alone_does_not_erase_a_configured_backup_dir(monkeypatch, tmp_path):
    """Pins the field-level merge _write_backup_config's own docstring names
    as the likeliest bug in it: --set-backup-keep run on its own, on a later
    occasion than --set-backup-dir, must not blank the directory back to the
    default beside the database -- and the reverse must hold too."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.backup import config as backup_config_module
    from sensei_top.backup.config import BACKUP_DIR_ENV

    monkeypatch.delenv(BACKUP_DIR_ENV, raising=False)

    cli_module._write_backup_config(directory=str(tmp_path / "custom-backups"))
    cli_module._write_backup_config(keep=5)

    cfg = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert cfg.directory == tmp_path / "custom-backups"
    assert cfg.keep == 5

    # And the reverse: setting the directory again afterwards must not
    # erase the keep count set moments ago.
    cli_module._write_backup_config(directory=str(tmp_path / "another-dir"))
    cfg_again = backup_config_module.resolve(tmp_path / "data" / "sensei-top.db")
    assert cfg_again.directory == tmp_path / "another-dir"
    assert cfg_again.keep == 5


def test_config_subcommand_rejects_an_invalid_coach_effort(capsys):
    parser = cli_module.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["config", "--set-coach-effort", "not-a-level"])


def test_config_shows_mtgo_not_configured_and_names_the_fix(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    parser = cli_module.build_parser()
    args = parser.parse_args(["config"])
    args.func(args)

    out = capsys.readouterr().out
    assert "No MTGO handle configured" in out
    assert "--set-mtgo-handle" in out


def test_config_shows_the_configured_mtgo_handle_in_full(monkeypatch, tmp_path, capsys):
    """The handle is the user's own account name, not a secret -- it must
    print in full, unlike the two API keys shown elsewhere in this output."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_mtgo_config(handle="Player1")

    parser = cli_module.build_parser()
    args = parser.parse_args(["config"])
    args.func(args)

    out = capsys.readouterr().out
    assert "MTGO handle source:" in out
    assert "Player1" in out


def test_config_set_mtgo_handle_flag_writes_and_preserves_claude_key(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_llm_config(api_key="base-key", model=None, effort=None)

    from sensei_top.mtgo.config import load_handle

    parser = cli_module.build_parser()
    args = parser.parse_args(["config", "--set-mtgo-handle", "Player1"])
    args.func(args)

    assert load_handle() == "Player1"
    assert llm_config_module.load().api_key == "base-key"


# --- mtgo/config.py: resolve_log_dir() -------------------------------------


def test_resolve_log_dir_env_wins_over_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(directory=str(tmp_path / "from-config"))
    env_dir = tmp_path / "from-env"
    monkeypatch.setenv("MTGO_LOG_DIR", str(env_dir))

    directory, source = resolve_log_dir()
    assert directory == env_dir
    assert source == "$MTGO_LOG_DIR"


def test_resolve_log_dir_reads_the_config_file_alone(monkeypatch, tmp_path):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(directory=str(tmp_path / "from-config"))

    directory, source = resolve_log_dir()
    assert directory == tmp_path / "from-config"
    assert source == "config.toml [mtgo] dir"


def test_resolve_log_dir_expands_a_tilde_in_the_env_var(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # expanduser on Windows
    monkeypatch.setenv("MTGO_LOG_DIR", "~/mtgo-share")
    from sensei_top.mtgo.config import resolve_log_dir

    directory, source = resolve_log_dir()
    assert directory == fake_home / "mtgo-share"
    assert source == "$MTGO_LOG_DIR"


def test_resolve_log_dir_empty_env_falls_through_to_config(monkeypatch, tmp_path):
    monkeypatch.setenv("MTGO_LOG_DIR", "")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(directory=str(tmp_path / "from-config"))

    directory, source = resolve_log_dir()
    assert directory == tmp_path / "from-config"
    assert source == "config.toml [mtgo] dir"


def test_resolve_log_dir_is_none_and_silent_with_no_config_file(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert caplog.messages == []


def test_resolve_log_dir_is_none_and_silent_with_a_handle_only_table(monkeypatch, tmp_path, caplog):
    """An install that configured an MTGO handle but never a directory (the
    common case -- plenty of installs stay Arena-only) must resolve
    silently, not warn -- unlike a config file that's actually broken."""
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    cli_module._write_mtgo_config(handle="Player1")

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert caplog.messages == []


def test_resolve_log_dir_warns_on_an_empty_dir_value(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('[mtgo]\ndir = ""\n')

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert any("not a usable path" in message for message in caplog.messages)


def test_resolve_log_dir_warns_on_a_non_string_dir_value(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("[mtgo]\ndir = 42\n")

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert any("not a usable path" in message for message in caplog.messages)


def test_resolve_log_dir_warns_on_unreadable_toml(monkeypatch, tmp_path, caplog):
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from sensei_top.mtgo.config import resolve_log_dir

    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text("this is not { valid toml at all")

    with caplog.at_level("WARNING"):
        result = resolve_log_dir()

    assert result is None
    assert any("could not read" in message for message in caplog.messages)


# --- cli.py: the config subcommand's --set-mtgo-dir flag -------------------


def test_config_set_mtgo_dir_flag_writes_the_resolved_path(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.mtgo.config import resolve_log_dir

    share = tmp_path / "mtgo-share"
    share.mkdir()

    parser = cli_module.build_parser()
    args = parser.parse_args(["config", "--set-mtgo-dir", str(share)])
    args.func(args)

    out = capsys.readouterr().out
    assert f"MTGO log directory written to {llm_config_module.config_path()} (mode 600)." in out

    directory, source = resolve_log_dir()
    assert directory == share.resolve()
    assert source == "config.toml [mtgo] dir"


def test_config_set_mtgo_dir_flag_on_a_directory_that_does_not_exist_yet(
    monkeypatch, tmp_path, capsys
):
    """A share mounted later is the normal case (cmd_config's --set-mtgo-dir
    branch) -- the value is still stored, with a note rather than a
    refusal."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from sensei_top.mtgo.config import resolve_log_dir

    not_yet_mounted = tmp_path / "not-mounted-yet"

    parser = cli_module.build_parser()
    args = parser.parse_args(["config", "--set-mtgo-dir", str(not_yet_mounted)])
    args.func(args)

    out = capsys.readouterr().out
    assert "does not exist yet; stored anyway" in out
    assert "MTGO log directory written to" in out

    directory, _source = resolve_log_dir()
    assert directory == not_yet_mounted.resolve()


def test_config_status_names_the_mtgo_directory_and_its_source(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TOPDECK_API_KEY", raising=False)
    monkeypatch.delenv("MTGO_HANDLE", raising=False)
    monkeypatch.delenv("MTGO_LOG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    cli_module._write_mtgo_config(directory=str(tmp_path / "mtgo-share"))

    parser = cli_module.build_parser()
    args = parser.parse_args(["config"])
    args.func(args)

    out = capsys.readouterr().out
    assert "MTGO directory source: config.toml" in out
    assert str(tmp_path / "mtgo-share") in out


def test_strict_schema_adds_additional_properties_at_every_object_level():
    from sensei_top.guide.narrative import _GUIDE_TOOL

    schema = strict_schema(_GUIDE_TOOL["input_schema"])
    assert schema["additionalProperties"] is False
    assert schema["properties"]["card_notes"]["items"]["additionalProperties"] is False
    matchup_items = schema["properties"]["matchups"]["items"]
    assert matchup_items["additionalProperties"] is False
    assert matchup_items["properties"]["board_in"]["items"]["additionalProperties"] is False


def test_strict_schema_does_not_mutate_its_argument():
    """_GUIDE_TOOL is the documented import contract -- a caller building a
    strict copy for structured outputs must never see the original schema
    change shape underneath it."""
    from sensei_top.guide.narrative import _GUIDE_TOOL

    before = json.dumps(_GUIDE_TOOL["input_schema"], sort_keys=True)
    strict_schema(_GUIDE_TOOL["input_schema"])
    after = json.dumps(_GUIDE_TOOL["input_schema"], sort_keys=True)
    assert before == after


def test_context_hash_is_a_plain_sha256_of_the_context_string():
    assert context_hash("hello") == hashlib.sha256(b"hello").hexdigest()


# --- the three POST .../narrative routes ---------------------------------


@pytest.fixture
def client(tmp_path, make_client):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    with make_client(create_app(db_path)) as c:
        yield c


@pytest.fixture
def guide_key(client):
    return client.get("/api/guide/decks").json()[0]["key"]


def test_no_credential_means_no_client_is_constructed(monkeypatch, client, guide_key):
    """The guarantee AGENTS.md non-negotiable #5 now rests on: with nothing
    configured, none of the three generate routes may even try to build an
    Anthropic client, let alone open a socket."""
    monkeypatch.setattr(llm_config_module, "load", lambda: None)

    def _boom(*args, **kwargs):
        raise AssertionError("write_prose/write_json ran with no credential configured")

    monkeypatch.setattr(llm_client_module, "write_prose", _boom)
    monkeypatch.setattr(llm_client_module, "write_json", _boom)

    for path in (
        f"/api/matches/{MATCH_WIN}/report/narrative",
        "/api/review/leaks/narrative",
        f"/api/guide/{guide_key}/narrative",
        f"/api/guide/{guide_key}/rcq/narrative",
    ):
        resp = client.post(path, json={"decklist": "4 Island", "expected": []})
        assert resp.status_code == 503
        assert "config --set-key" in resp.json()["detail"]


def test_generate_match_report_narrative_stores_and_returns_it(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(
        llm_client_module, "write_prose",
        lambda prompt, *, cfg, label: Completion(
            text="You won because of X.", model="claude-opus-5",
            input_tokens=500, output_tokens=200, cost_usd=0.0075,
        ),
    )

    resp = client.post(f"/api/matches/{MATCH_WIN}/report/narrative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["narrative"] == "You won because of X."
    assert body["cost_usd"] == pytest.approx(0.0075)

    again = client.get(f"/api/matches/{MATCH_WIN}/report/narrative").json()
    assert again["status"] == "ok"
    assert again["narrative"] == "You won because of X."
    assert again["stale"] is False


def test_generate_match_report_narrative_404s_with_nothing_to_narrate(monkeypatch, client):
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(
        matches_routes, "build_match_report",
        lambda conn, match_id, **kwargs: SimpleNamespace(
            findings=(), gaps=(), games=(), result=None,
        ),
    )
    resp = client.post(f"/api/matches/{MATCH_WIN}/report/narrative")
    assert resp.status_code == 404


def test_generate_leaks_narrative_stores_and_returns_it(monkeypatch, client):
    from sensei_top.review.leaks import Leak

    fake_leak = Leak(
        code="mana_screwed", category="deckbuilding", sample_title="Stuck on lands",
        n_with=15, win_rate_with=0.3, ci_with=(0.15, 0.5),
        n_without=40, win_rate_without=0.55, ci_without=(0.4, 0.7),
        gap=0.25, match_ids_with=("m1",),
    )
    monkeypatch.setattr(review_routes, "find_leaks", lambda conn, **kwargs: [fake_leak])
    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    monkeypatch.setattr(
        llm_client_module, "write_prose",
        lambda prompt, *, cfg, label: Completion(
            text="Work on mulligans.", model="claude-opus-5",
            input_tokens=300, output_tokens=100, cost_usd=0.004,
        ),
    )

    resp = client.post("/api/review/leaks/narrative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["narrative"] == "Work on mulligans."

    again = client.get("/api/review/leaks/narrative").json()
    assert again["status"] == "ok"
    assert again["narrative"] == "Work on mulligans."


def test_generate_guide_narrative_converges_with_the_hand_import_parser(
    monkeypatch, client, guide_key
):
    """The whole reason the generate path is safe: a ``write_json`` payload
    shaped like ``_GUIDE_TOOL``'s schema must parse through the exact same
    ``guide_narrative_from_json`` the CLI import uses, and land in both
    ``deck_narrative`` and ``matchup_brief`` — proving the generate path and
    the hand-import path converge on one validator, not two."""
    conn = sqlite3.connect(client.app.state.database)
    conn.execute(
        "INSERT INTO meta_event (event_id, path, blob_sha, source, name, event_date, "
        "format, tier) VALUES ('e', 'p', 's', 'mtgo', 'e', '2026-08-15', 'Standard', 'B')"
    )
    conn.execute(
        "INSERT INTO meta_deck (event_id, deck_ord, mainboard_json, sideboard_json, wins, "
        "losses) VALUES ('e', 0, '[]', '[]', 5, 0)"
    )
    conn.execute(
        "INSERT INTO meta_deck_archetype (event_id, deck_ord, archetype_key, archetype_name, "
        "label, method, classified_at) VALUES ('e', 0, 'boros_convoke', 'Boros Convoke', "
        "'Boros Convoke', 'archetype', 'now')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(llm_config_module, "load", lambda: LLMConfig(api_key="k"))
    payload = {
        "engine": "Cheap spells trigger prowess.",
        "fix": "Deploy earlier.",
        "card_notes": [],
        "matchups": [{
            "archetype": "Boros Convoke", "prose": "Board in sweepers.",
            "board_in": [], "board_out": [],
        }],
        "checklist": ["Am I racing?"],
    }
    monkeypatch.setattr(
        llm_client_module, "write_json",
        lambda prompt, schema, *, cfg, label: Completion(
            text=json.dumps(payload), model="claude-opus-5",
            input_tokens=2000, output_tokens=1500, cost_usd=0.0475,
        ),
    )

    resp = client.post(f"/api/guide/{guide_key}/narrative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["guide"]["engine"] == "Cheap spells trigger prowess."
    assert body["cost_usd"] == pytest.approx(0.0475)

    conn = sqlite3.connect(client.app.state.database)
    conn.row_factory = sqlite3.Row
    narrative_row = conn.execute(
        "SELECT * FROM deck_narrative WHERE deck_key = ?", (guide_key,)
    ).fetchone()
    assert narrative_row is not None
    assert narrative_row["cost_usd"] == pytest.approx(0.0475)

    brief_row = conn.execute(
        "SELECT * FROM matchup_brief WHERE deck_key = ? AND archetype_key = 'boros_convoke'",
        (guide_key,),
    ).fetchone()
    assert brief_row is not None
    assert brief_row["prose"] == "Board in sweepers."
    conn.close()


# --- config_path() on Windows (release plan 3, D6) --------------------------
# These monkeypatch sys.platform and the environment into tmp_path trees, so
# on real Windows they exercise the same branch; none needs to skip there.


def _windows_env(monkeypatch, tmp_path):
    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    home.mkdir()
    appdata.mkdir()
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(llm_config_module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(llm_config_module, "_warned_old_config", False)
    return home / ".config" / "sensei-top" / "config.toml", appdata / "sensei-top" / "config.toml"


def test_windows_config_lives_in_appdata(monkeypatch, tmp_path):
    _old, new = _windows_env(monkeypatch, tmp_path)
    assert llm_config_module.config_path() == new


def test_windows_falls_back_to_the_old_file_and_warns_once(monkeypatch, tmp_path, caplog):
    old, new = _windows_env(monkeypatch, tmp_path)
    old.parent.mkdir(parents=True)
    old.write_text('[claude]\napi_key = "old-key"\n')
    with caplog.at_level("WARNING", logger=llm_config_module.log.name):
        assert llm_config_module.config_path() == old
        assert load() == LLMConfig(api_key="old-key")
    warnings = [r.getMessage() for r in caplog.records if "now belongs at" in r.getMessage()]
    assert warnings == [
        f"config file read from {old}; on Windows it now belongs at {new}, so move it there"
    ]
    assert not new.exists()


def test_windows_new_file_wins_over_the_old_one(monkeypatch, tmp_path, caplog):
    old, new = _windows_env(monkeypatch, tmp_path)
    for path in (old, new):
        path.parent.mkdir(parents=True)
    old.write_text('[claude]\napi_key = "old-key"\n')
    new.write_text('[claude]\napi_key = "new-key"\n')
    assert llm_config_module.config_path() == new
    assert load().api_key == "new-key"
    assert not [r for r in caplog.records if "now belongs at" in r.getMessage()]


def test_xdg_config_home_wins_on_windows_too(monkeypatch, tmp_path):
    _windows_env(monkeypatch, tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert llm_config_module.config_path() == tmp_path / "xdg" / "sensei-top" / "config.toml"


def test_non_windows_keeps_dot_config_even_with_appdata_set(monkeypatch, tmp_path):
    old, _new = _windows_env(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_config_module.sys, "platform", "linux")
    assert llm_config_module.config_path() == old
