"""The only module in this project that imports ``anthropic``.

Three entry points: two for free-form prose (the match report, the leak
finder) and structured guide answers, and one for the coach report, which
adds the server-side web search tool. All three stream — a guide generation
at ``effort: high`` genuinely runs for minutes, well past what a
non-streaming request can wait out — and all three return a ``Completion``
carrying its own measured cost, never a guessed one (AGENTS.md
non-negotiable #4 applies to money the same as it applies to match data).

Every route that calls in here has already checked ``llm.config.load()`` (or
``load_coach()``) is not ``None``; nothing in this module resolves
credentials itself.
"""

from __future__ import annotations

import copy
import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

import anthropic

from sensei_top.llm.config import LLMConfig

__all__ = [
    "REPORT_MODELS",
    "Citation",
    "Completion",
    "LLMError",
    "price_per_mtok",
    "strict_schema",
    "write_json",
    "write_prose",
    "write_report",
]

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

MAX_TOKENS = 32000

# $ per 1M tokens, (input, output, cache write 5 min, cache read). An
# unpriced model prices its call NULL rather than a guessed number (AGENTS.md
# non-negotiable #4/#5 — "cost is measured, never estimated" applies here
# too). Every column is confirmed against the live pricing page,
# platform.claude.com/docs/en/about-claude/pricing ("5m cache writes" and
# "Cache hits and refreshes"), 2026-10-07: a five-minute write is 1.25x
# input; a cache read is 0.05x input on Opus 5.5, 0.025x on Fable 5.1 and
# 0.1x on the rest.
_PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-fable-5-1": (10.00, 50.00, 12.50, 0.25),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
}

# $10 per 1,000 web searches (platform.claude.com/docs/en/agents-and-tools/
# tool-use/web-search-tool: "Web search usage is charged at $10 per 1,000
# searches"). Confirmed against the live docs 2026-09-18.
_SEARCH_COST_PER_1000 = 10.0

# Models that get the dynamic-filtering web search tool
# (``web_search_20260209``) rather than the basic one. Per the live
# web-search-tool doc, "Claude 4.6 and later models" qualify; every other
# model (including claude-haiku-4-5 and anything unrecognized) gets
# ``web_search_20250305`` instead.
_DYNAMIC_FILTERING_MODELS = frozenset(
    {"claude-opus-5", "claude-opus-5-5", "claude-fable-5-1", "claude-sonnet-5"}
)

# The models the coach's dashboard dropdown may ask ``write_report`` to use
# (``api/routes/coach.py``'s ``POST .../narrative``), in the order the
# dropdown lists them, with display labels. Each one is priced (``_PRICES``),
# gets the dynamic-filtering search tool (``_DYNAMIC_FILTERING_MODELS``), and
# accepts what ``write_report`` always sends: ``thinking={"type": "adaptive"}``
# plus an explicit ``output_config.effort``. Haiku 4.5 is priced above but
# deliberately excluded here — it rejects adaptive thinking and an explicit
# effort outright, so it can't take a coach call regardless of price. Opus
# 5.5's own default effort is ``medium``, but that default never applies:
# every call through this module sends effort explicitly.
REPORT_MODELS: dict[str, str] = {
    "claude-opus-5": "Opus 5",
    "claude-opus-5-5": "Opus 5.5",
    "claude-fable-5-1": "Fable 5.1",
    "claude-sonnet-5": "Sonnet 5",
}

_MAX_PAUSE_TURN_CONTINUATIONS = 3


class LLMError(Exception):
    """Raised for anything a route should turn into a clean 502 — a safe
    message to render in the dashboard, never a raw SDK exception."""


@dataclass(frozen=True, slots=True)
class Citation:
    """One deduplicated web citation, keyed by URL by the caller. Field
    names and nullability match the SDK's
    ``CitationsWebSearchResultLocation`` (``anthropic.types``):
    ``url``/``cited_text`` are always present, ``title`` is optional."""

    url: str
    title: str | None
    cited_text: str


@dataclass(frozen=True, slots=True)
class Completion:
    """``input_tokens`` is the API's own field: the **uncached remainder** of
    the prompt. The prompt's whole size is it plus the two cache counts,
    which stay ``0`` for every call that marks nothing for caching (only
    ``write_report`` does)."""

    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float | None
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    web_search_requests: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def _cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    web_search_requests: int = 0,
    *,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float | None:
    prices = _PRICES.get(model)
    if prices is None:
        return None
    in_price, out_price, write_price, read_price = prices
    token_cost = (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_creation_input_tokens * write_price
        + cache_read_input_tokens * read_price
    ) / 1_000_000
    search_cost = web_search_requests * _SEARCH_COST_PER_1000 / 1000
    return token_cost + search_cost


def price_per_mtok(model: str) -> tuple[float, float] | None:
    """``(input, output)`` $/MTok for ``model``, or ``None`` when unpriced —
    the dashboard's own read of ``_PRICES``, so the Coach tab's model
    dropdown can show a cost per option without this module handing out its
    private dict. The cache columns stay private: the dropdown prices
    tokens, not a cache the model may or may not hit."""
    prices = _PRICES.get(model)
    return None if prices is None else (prices[0], prices[1])


def _cache_counts(usage: anthropic.types.Usage) -> tuple[int, int]:
    """``(cache_creation_input_tokens, cache_read_input_tokens)`` from one
    response's ``usage``, ``None`` read as ``0``. That is a measurement, not
    a guess: the SDK's ``Usage`` always carries both fields and leaves them
    ``None`` when the request touched no cache, and a request that touched
    no cache wrote and read zero tokens of it."""
    return usage.cache_creation_input_tokens or 0, usage.cache_read_input_tokens or 0


def _run(client: anthropic.Anthropic, **kwargs: object) -> anthropic.types.Message:
    try:
        with client.messages.stream(**kwargs) as stream:  # type: ignore[arg-type]
            return stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise LLMError("The configured Claude credential was rejected.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Claude API rate limit hit — try again shortly.") from exc
    except anthropic.APIStatusError as exc:
        message = (exc.message or "").lower()
        if exc.status_code == 400 and ("web search" in message or "web_search" in message):
            # An org-level "web search disabled" rejection: point at the
            # coach-specific escape hatch rather than the generic message
            # below.
            raise LLMError(
                "Claude API rejected the web search tool (likely disabled for "
                "this organization) — run `sensei-top config "
                "--coach-web-search off` to disable it for the coach."
            ) from exc
        raise LLMError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("Could not reach the Claude API.") from exc


def _completion(message: anthropic.types.Message) -> Completion:
    if message.stop_reason == "refusal":
        category = message.stop_details.category if message.stop_details else None
        raise LLMError(f"Claude declined this request (category: {category}).")

    text = "".join(block.text for block in message.content if block.type == "text")
    usage = message.usage
    cache_creation, cache_read = _cache_counts(usage)
    return Completion(
        text=text,
        model=message.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=_cost(
            message.model,
            usage.input_tokens,
            usage.output_tokens,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
        ),
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )


def strict_schema(schema: dict) -> dict:
    """A deep copy of ``schema`` with ``additionalProperties: false`` added
    to every object node, for Anthropic's strict structured-output mode.
    Never mutates its argument — callers pass in schemas that double as an
    import contract elsewhere (``guide/narrative.py``'s ``_GUIDE_TOOL``) and
    must not see it change shape underneath them."""
    result = copy.deepcopy(schema)

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node.setdefault("additionalProperties", False)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(result)
    return result


def _call(prompt: str, *, cfg: LLMConfig, label: str, output_config: dict) -> Completion:
    client = anthropic.Anthropic(api_key=cfg.api_key, timeout=600.0)
    log.info("Calling Claude for %s (model=%s, effort=%s)", label, cfg.model, cfg.effort)
    started = time.monotonic()
    try:
        message = _run(
            client,
            model=cfg.model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config=output_config,
            messages=[{"role": "user", "content": prompt}],
        )
        completion = _completion(message)
    except LLMError:
        log.warning("Claude call for %s failed after %.1fs", label, time.monotonic() - started)
        raise
    log.info(
        "Claude call for %s complete: %d in (+%d cache write, %d cache read) / %d out "
        "tokens, %s, %.1fs",
        label,
        completion.input_tokens,
        completion.cache_creation_input_tokens,
        completion.cache_read_input_tokens,
        completion.output_tokens,
        f"${completion.cost_usd:.4f}" if completion.cost_usd is not None else "cost unknown",
        time.monotonic() - started,
    )
    return completion


def write_prose(prompt: str, *, cfg: LLMConfig, label: str) -> Completion:
    return _call(prompt, cfg=cfg, label=label, output_config={"effort": cfg.effort})


def write_json(prompt: str, schema: dict, *, cfg: LLMConfig, label: str) -> Completion:
    """Like ``write_prose``, but constrains the response to ``schema`` via
    structured outputs. The caller is responsible for making ``schema``
    strict (``additionalProperties: false`` throughout) — this function does
    not mutate what it is given."""
    return _call(
        prompt, cfg=cfg, label=label,
        output_config={"effort": cfg.effort, "format": {"type": "json_schema", "schema": schema}},
    )


def write_report(
    prompt: str,
    *,
    cfg: LLMConfig,
    label: str,
    allowed_domains: Sequence[str],
    max_searches: int = 8,
) -> Completion:
    """Like ``write_prose``, but for the coach report: adds the server-side
    web search tool (restricted to ``allowed_domains``) when ``cfg.web_search``
    is on, and follows the ``pause_turn`` server-tool loop through to
    completion. Never passes ``output_config.format`` — structured output
    and web search are not known to interact safely together.

    A ``pause_turn`` response is continued by re-sending the paused
    assistant message unchanged, appended to ``messages``, with the same
    ``tools`` array. Each response in the loop carries only its own new
    blocks, not a repeat of earlier ones, so usage, text and citations below
    are accumulated across every response, not read from the final one
    alone.
    """
    client = anthropic.Anthropic(api_key=cfg.api_key, timeout=600.0)

    tools: list[dict] = []
    if cfg.web_search:
        # web_search_20260209 (dynamic filtering) runs search plus code
        # execution server-side automatically; per server-tools.md's
        # "Dynamic filtering with code execution" section, "there are no
        # additional charges for code execution calls made this way beyond
        # the standard token costs" — so web_search_requests (below) is the
        # only extra billed quantity, same as the basic tool.
        tool_type = (
            "web_search_20260209"
            if cfg.model in _DYNAMIC_FILTERING_MODELS
            else "web_search_20250305"
        )
        tools.append(
            {
                "type": tool_type,
                "name": "web_search",
                "max_uses": max_searches,
                "allowed_domains": list(allowed_domains),
            }
        )

    log.info(
        "Calling Claude for %s (model=%s, effort=%s, web_search=%s)",
        label, cfg.model, cfg.effort, cfg.web_search,
    )
    started = time.monotonic()

    messages: list[dict] = [{"role": "user", "content": prompt}]
    texts: list[str] = []
    citations: dict[str, Citation] = {}
    input_tokens = 0
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0
    output_tokens = 0
    web_search_requests = 0
    model_seen = cfg.model
    continuations = 0
    # Diagnostic for docs/coach.md's "no web citations are stored" gap: every
    # content block type seen across the whole loop, and how many text
    # blocks actually carried a non-empty `citations` list. Confirms or
    # refutes the dynamic-filtering hypothesis on the next real run rather
    # than guessing at it (AGENTS.md non-negotiable #4).
    block_type_counts: Counter[str] = Counter()
    cited_text_blocks = 0

    try:
        while True:
            kwargs: dict[str, object] = {
                "model": cfg.model,
                "max_tokens": MAX_TOKENS,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": cfg.effort},
                "messages": messages,
                # Automatic caching, five-minute TTL: the one call that
                # re-reads its own prefix (search iterations, pause_turn
                # re-sends). Why no other call is marked: docs/llm.md's
                # caching paragraph.
                "cache_control": {"type": "ephemeral"},
            }
            if tools:
                kwargs["tools"] = tools
            message = _run(client, **kwargs)

            model_seen = message.model
            usage = message.usage
            input_tokens += usage.input_tokens
            cache_creation, cache_read = _cache_counts(usage)
            cache_creation_input_tokens += cache_creation
            cache_read_input_tokens += cache_read
            output_tokens += usage.output_tokens
            if usage.server_tool_use is not None:
                web_search_requests += usage.server_tool_use.web_search_requests

            for block in message.content:
                block_type_counts[block.type] += 1
                if block.type == "text":
                    texts.append(block.text)
                    if block.citations:
                        cited_text_blocks += 1
                    for citation in block.citations or ():
                        if citation.type == "web_search_result_location":
                            citations.setdefault(
                                citation.url,
                                Citation(
                                    url=citation.url,
                                    title=citation.title,
                                    cited_text=citation.cited_text,
                                ),
                            )
                elif block.type == "web_search_tool_result":
                    content = block.content
                    if getattr(content, "type", None) == "web_search_tool_result_error":
                        # HTTP 200 with an error object in `content`, per
                        # web-search-tool.md's error-handling section — log
                        # and keep going rather than raising, the same
                        # fail-soft posture the rest of this module takes.
                        log.warning(
                            "Claude web search failed for %s: %s", label, content.error_code,
                        )

            if message.stop_reason == "refusal":
                category = message.stop_details.category if message.stop_details else None
                raise LLMError(f"Claude declined this request (category: {category}).")

            if message.stop_reason != "pause_turn":
                break

            continuations += 1
            if continuations > _MAX_PAUSE_TURN_CONTINUATIONS:
                log.warning(
                    "Claude web search loop for %s hit the %d-continuation cap; using what "
                    "we have.",
                    label, _MAX_PAUSE_TURN_CONTINUATIONS,
                )
                break

            messages.append({"role": "assistant", "content": message.content})
    except LLMError:
        log.warning("Claude call for %s failed after %.1fs", label, time.monotonic() - started)
        raise

    log.info(
        "Claude content blocks for %s: %s (%d/%d text blocks carried citations)",
        label, dict(block_type_counts), cited_text_blocks, block_type_counts.get("text", 0),
    )

    cost = _cost(
        model_seen,
        input_tokens,
        output_tokens,
        web_search_requests,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )
    completion = Completion(
        text="".join(texts),
        model=model_seen,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        citations=tuple(citations.values()),
        web_search_requests=web_search_requests,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )
    log.info(
        "Claude call for %s complete: %d in (+%d cache write, %d cache read) / %d out "
        "tokens, %d searches, %s, %.1fs",
        label,
        completion.input_tokens,
        completion.cache_creation_input_tokens,
        completion.cache_read_input_tokens,
        completion.output_tokens,
        completion.web_search_requests,
        f"${completion.cost_usd:.4f}" if completion.cost_usd is not None else "cost unknown",
        time.monotonic() - started,
    )
    return completion
