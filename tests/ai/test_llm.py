"""Tests for src/sensei_top/ai/llm/ — the opt-in Claude call AGENTS.md
non-negotiable #5 permits — and for the four ``POST .../narrative``
routes that resolve their credential through ``llm_config.load()``: the match
report, the leak finder, the deck guide and the RCQ guide (the coach's, the
fifth, resolves ``load_coach()``).

No test here ever makes a network call: ``llm/client.py`` is exercised
against a fake ``anthropic.Anthropic`` that never opens a socket, and the API
routes against monkeypatched ``llm_config.load`` / ``llm_client.write_prose``
/ ``llm_client.write_json``. The credential's own resolution is covered by
``tests/test_claude_config.py``.
``test_no_credential_means_no_client_is_constructed`` is the one that pins
the actual guarantee: with nothing configured, none of the four routes may
even try to build a client.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from sensei_top import claude_config as llm_config_module
from sensei_top.ai.llm import client as llm_client_module
from sensei_top.ai.llm.client import (
    Citation,
    LLMError,
    price_per_mtok,
    strict_schema,
    write_json,
    write_prose,
    write_report,
)
from sensei_top.ai.review.narrative_store import context_hash
from sensei_top.api import create_app
from sensei_top.claude_config import REPORT_MODELS, LLMConfig
from sensei_top.db import open_database
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file

FIXTURE = Path(__file__).parent.parent / "fixtures" / "match_session.log"
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"


def _write_latin1_config(tmp_path):
    """A config file saved in Latin-1 rather than UTF-8 — what an editor
    that defaults to the system code page writes for an accented value.
    ``tomllib`` raises ``UnicodeDecodeError`` on it, not ``TOMLDecodeError``."""
    config_dir = tmp_path / "sensei-top"
    config_dir.mkdir()
    path = config_dir / "config.toml"
    path.write_bytes(
        '[claude]\napi_key = "file-key"\n[mtgo]\nhandle = "Jos\xe9"\n'
        '[arena]\nlog = "/tmp/Player.log"\n[backup]\nkeep = "3"\n'
        '[topdeck]\napi_key = "td-key"\n'.encode("latin-1")
    )
    return path


def test_llm_status_answers_unconfigured_for_a_non_utf8_file(monkeypatch, tmp_path, make_client):
    _write_latin1_config(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    response = make_client(create_app(tmp_path / "unused.db")).get("/api/llm/status")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "model": None}


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
    cache_creation_input_tokens=None, cache_read_input_tokens=None,
):
    """``content_blocks`` overrides the single default text block entirely,
    for tests that need a ``web_search_tool_result`` block or more than one
    ``text`` block. ``web_search_requests`` populates
    ``usage.server_tool_use`` (``None`` when omitted, matching a real
    response that never called a server tool — ``Usage.server_tool_use`` is
    ``Optional`` in the SDK's own type). The two cache counts default to
    ``None`` the same way: the SDK's ``Usage`` declares both optional, and
    a request that touched no cache reports neither."""
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
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
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


def test_price_per_mtok_stays_a_two_tuple_for_every_priced_model():
    """The Coach page's dropdown reads ``(input, output)``; the cache columns
    ``_PRICES`` gained stay private."""
    for model in llm_client_module._PRICES:
        assert len(price_per_mtok(model)) == 2


def test_cost_prices_cache_writes_and_reads_for_a_priced_model():
    """Opus 5.5 is $4 in / $20 out / $5 per 5-minute cache write / $0.20 per
    cache read, per MTok (the pricing page, 2026-10-07). 1,000 in, 10,000
    written, 90,000 read and 2,000 out:
    (1000 x 4 + 10000 x 5 + 90000 x 0.2 + 2000 x 20) / 1e6
    = (4,000 + 50,000 + 18,000 + 40,000) / 1e6 = 0.112."""
    cost = llm_client_module._cost(
        "claude-opus-5-5", 1_000, 2_000,
        cache_creation_input_tokens=10_000, cache_read_input_tokens=90_000,
    )
    assert cost == pytest.approx(0.112)


def test_an_unpriced_model_with_cache_tokens_still_costs_none():
    cost = llm_client_module._cost(
        "some-future-model", 1_000, 2_000,
        cache_creation_input_tokens=10_000, cache_read_input_tokens=90_000,
    )
    assert cost is None


def test_cache_fields_reported_as_none_count_as_zero(monkeypatch):
    """A request that touched no cache reports both fields as ``None``:
    that is zero tokens written and read, not an error. Opus 5 at $5/$25,
    1M in + 1M out = $30, with nothing added for the cache."""
    _patch_client(
        monkeypatch,
        message=_fake_message(
            model="claude-opus-5", input_tokens=1_000_000, output_tokens=1_000_000,
            cache_creation_input_tokens=None, cache_read_input_tokens=None,
        ),
    )
    result = write_prose("p", cfg=LLMConfig(api_key="k"), label="test")
    assert result.cache_creation_input_tokens == 0
    assert result.cache_read_input_tokens == 0
    assert result.cost_usd == pytest.approx(30.0)


def test_write_prose_prices_cache_counts_the_response_reports(monkeypatch):
    """Nothing ``write_prose`` sends asks for a cache, but whatever ``usage``
    reports is still measured and priced, never dropped. Sonnet 5 is $2 in /
    $10 out / $2.50 write / $0.20 read per MTok: 1M of each
    = 2 + 10 + 2.5 + 0.2 = $14.70."""
    _patch_client(
        monkeypatch,
        message=_fake_message(
            model="claude-sonnet-5", input_tokens=1_000_000, output_tokens=1_000_000,
            cache_creation_input_tokens=1_000_000, cache_read_input_tokens=1_000_000,
        ),
    )
    result = write_prose("p", cfg=LLMConfig(api_key="k"), label="test")
    assert result.cache_creation_input_tokens == 1_000_000
    assert result.cache_read_input_tokens == 1_000_000
    assert result.cost_usd == pytest.approx(14.70)


def test_write_prose_and_write_json_send_no_cache_control(monkeypatch):
    """Single-call routes stay unmarked: a cache write with no read to pay
    it back costs 1.25x the input price."""
    captures: list[dict] = []
    _patch_client(monkeypatch, message=_fake_message(text='{"a": 1}'), captures=captures)
    write_prose("p", cfg=LLMConfig(api_key="k"), label="test")
    write_json("p", {"type": "object"}, cfg=LLMConfig(api_key="k"), label="test")
    assert len(captures) == 2
    assert all("cache_control" not in kwargs for kwargs in captures)


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


def test_write_report_marks_every_request_for_caching_and_sums_cache_counts(monkeypatch):
    """Every request in the pause_turn loop sends top-level automatic
    caching with the default five-minute TTL. Counts are summed across the
    loop: 8,000 + 0 written, 0 + 7,500 read. Cost, Opus 5 at $5 in / $25 out
    / $6.25 write / $0.50 read per MTok, no searches:
    in 1,200 + 300 = 1,500 → 1500 x 5 = 7,500
    out 400 + 100 = 500 → 500 x 25 = 12,500
    write 8,000 → 8000 x 6.25 = 50,000
    read 7,500 → 7500 x 0.5 = 3,750
    total 73,750 / 1e6 = 0.07375."""
    first = _fake_message(
        text="Partial. ", stop_reason="pause_turn",
        input_tokens=1_200, output_tokens=400,
        cache_creation_input_tokens=8_000, cache_read_input_tokens=0,
    )
    second = _fake_message(
        text="Done.", stop_reason="end_turn",
        input_tokens=300, output_tokens=100,
        cache_creation_input_tokens=None, cache_read_input_tokens=7_500,
    )
    captures: list[dict] = []
    _patch_client(monkeypatch, messages=[first, second], captures=captures)

    result = write_report(
        "p", cfg=LLMConfig(api_key="k"), label="coach", allowed_domains=["mtggoldfish.com"]
    )

    assert len(captures) == 2
    assert all(kwargs["cache_control"] == {"type": "ephemeral"} for kwargs in captures)
    assert result.input_tokens == 1_500
    assert result.cache_creation_input_tokens == 8_000
    assert result.cache_read_input_tokens == 7_500
    assert result.cost_usd == pytest.approx(0.07375)


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
            cache_creation_input_tokens=None, cache_read_input_tokens=None,
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
    with pytest.raises(LLMError, match="web_search = false"):
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


def test_load_coach_returns_none_with_no_credential_and_builds_no_client(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    def _boom(**_):
        raise AssertionError("anthropic.Anthropic constructed with no credential")

    monkeypatch.setattr(llm_client_module.anthropic, "Anthropic", _boom)
    assert llm_config_module.load_coach() is None


def test_strict_schema_adds_additional_properties_at_every_object_level():
    from sensei_top.ai.guide.narrative import _GUIDE_TOOL

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
    from sensei_top.ai.guide.narrative import _GUIDE_TOOL

    before = json.dumps(_GUIDE_TOOL["input_schema"], sort_keys=True)
    strict_schema(_GUIDE_TOOL["input_schema"])
    after = json.dumps(_GUIDE_TOOL["input_schema"], sort_keys=True)
    assert before == after


def test_context_hash_is_a_plain_sha256_of_the_context_string():
    assert context_hash("hello") == hashlib.sha256(b"hello").hexdigest()


# --- the four credential-gated POST .../narrative routes -------------------


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
    configured, none of the four generate routes may even try to build an
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
