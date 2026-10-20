"""Shared plumbing for the ``.../narrative`` routes and the paste ``PUT``s
(``docs/llm.md``, "What calls out, and what it sends").

The match report and the leak finder are the same shape end to end: build
some evidence, wrap it in a prompt, and — on ``POST`` with a credential
configured — send it through ``llm.write_prose`` and store the prose
verbatim. ``NarrativeSpec`` plus ``narrative_get``/``narrative_post`` cover
both; ``routes/matches.py`` and ``routes/review.py`` supply only the
per-route closures (which evidence, which store).

The deck guide and the RCQ guide are the JSON-schema-answer relatives: each
builds the finished prompt directly rather than a separate context object,
and its ``POST`` parses a structured answer instead of storing prose; the
deck guide's also writes a second table (``matchup_brief``) in the same
transaction. Forcing them through ``NarrativeSpec`` would cost more in
indirection than it saves, so they share only ``require_credential``'s 503
and ``run_authored_write``'s transaction. The coach (``routes/coach.py``)
resolves its own credential and shares ``no_credential_detail``,
``run_authored_write`` and the paste helpers.

**The paste helpers**: every ``PUT`` that stores a pasted answer (the
match report, the leak finder, the coach, the deck guide, a brief, the
coverage card and the RCQ guide) shares ``refusal``, ``check_pasted_length``,
``read_pasted``, ``read_pasted_prose`` (the three prose cards) and
``unreadable_answer``, so each refuses an answer with the same status and
the same keyed sentence, and none calls a model.

**Why this module calls ``sensei_top.llm`` through its modules**:
``tests/test_llm.py`` patches ``load``, ``write_prose`` and ``write_json``
on ``sensei_top.llm.config``/``sensei_top.llm.client`` themselves, and this
file calls them as ``llm_config.load``/``llm_client.write_prose``, so the
patch reaches it. A name imported *by name* into a route module
(``review.py``'s ``find_leaks``, say) is patched on that route module, so it
has to stay called from that module's own closures.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from sensei_top.answers import (
    Answer,
    AnswerError,
    check_length,
    prose_of,
    read_answer,
    unreadable,
)
from sensei_top.i18n import N_, _
from sensei_top.llm import client as llm_client
from sensei_top.llm import config as llm_config
from sensei_top.llm.client import Completion, LLMConfig

NO_CREDENTIAL_DETAIL = N_("No Claude credential configured. Run 'sensei-top config --set-key'.")


def no_credential_detail() -> str:
    """The 503's detail in the request language. Callers use this rather
    than wrapping the constant, which a module that only imports it cannot
    do."""
    return _(NO_CREDENTIAL_DETAIL)


def refusal(exc: AnswerError) -> HTTPException:
    """The HTTP refusal for an answer that cannot be stored: 422, or 413 for
    one over the size limit. The detail is the sentence in the request's
    language; nothing is stored."""
    return HTTPException(status_code=exc.status, detail=exc.message)


def check_pasted_length(raw: str) -> None:
    """413 for a body over ``MAX_ANSWER_BYTES``; first, before any lookup."""
    try:
        check_length(raw)
    except AnswerError as exc:
        raise refusal(exc) from exc


def read_pasted(raw: str, expected_for: str) -> Answer:
    """A pasted answer read through the contract, header required (the
    dashboard's; the CLI imports accept an older answer without one)."""
    try:
        return read_answer(raw, expected_for, require_header=True)
    except AnswerError as exc:
        raise refusal(exc) from exc


def read_pasted_prose(raw: str, expected_for: str) -> tuple[Answer, str]:
    """A pasted answer for a prose card (match report, training plan,
    coach) and its prose: ``read_pasted``'s refusals, then 422 for a body
    with no ``"prose"`` string or with only whitespace in it."""
    answer = read_pasted(raw, expected_for)
    try:
        return answer, prose_of(answer)
    except AnswerError as exc:
        raise refusal(exc) from exc


def unreadable_answer(exc: Exception) -> HTTPException:
    """422 for a body its card's own parser rejected, with the parser's
    message (English, as on the CLI) under the keyed sentence."""
    return refusal(unreadable(str(exc)))


@dataclass(frozen=True, slots=True)
class NarrativeEnvelope:
    """What the match report's and the leak finder's ``NarrativeResponse``
    is built from; the route maps ``who``/``when`` onto ``model``/
    ``generated_at``."""

    status: str
    content: Any = None
    prompt: str | None = None
    who: str | None = None
    when: str | None = None
    cost_usd: float | None = None
    stale: bool = False


def require_credential() -> LLMConfig:
    """The identical 503 the match-report, leak-finder, deck-guide and RCQ
    ``POST .../narrative`` routes raise with nothing configured (the coach
    resolves ``load_coach()`` itself) —
    ``tests/test_llm.py::test_no_credential_means_no_client_is_constructed``
    pins the status code and the detail's ``config --set-key``."""
    cfg = llm_config.load()
    if cfg is None:
        raise HTTPException(status_code=503, detail=no_credential_detail())
    return cfg


def run_authored_write(conn: sqlite3.Connection, write: Callable[[], None]) -> None:
    """The ``BEGIN``/``COMMIT``/``ROLLBACK`` wrapper the narrative and paste
    routes use: ``api/deps.py::get_writable_conn`` opens in autocommit mode,
    where a bare ``conn.commit()`` is a no-op on a write that already landed.
    Takes a callback rather than one hardcoded statement because the guide
    routes' write touches two tables (``deck_narrative`` and
    ``matchup_brief``) that must land together or not at all.
    """
    conn.execute("BEGIN")
    try:
        write()
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


@dataclass(frozen=True, slots=True)
class NarrativeSpec:
    """Everything a prose narrative route (the match report, the leak
    finder) needs beyond the shared control flow below. ``full_prompt`` is
    what ``POST`` sends the model; ``copied_prompt`` is what ``GET`` offers
    to copy, the same text plus the answer contract. Built fresh per
    request by a small helper in the route module that closes over that
    request's own ``conn`` and path params, so this stays a plain function
    rather than a FastAPI dependency.
    """

    build_context: Callable[[], Any]
    full_prompt: Callable[[Any], str]
    copied_prompt: Callable[[Any], str]
    read_stored: Callable[[], Any]
    context_hash: Callable[[Any], str]
    no_context_detail: str
    label: str


def narrative_get(spec: NarrativeSpec) -> NarrativeEnvelope:
    """``GET .../narrative``: the stored prose plus the prompt to (re)write
    it from (the copyable one, with the answer contract), always a 200 —
    'nothing to narrate' and 'nothing stored yet' are both ordinary
    outcomes for an opt-in feature, never errors."""
    context = spec.build_context()
    if context is None:
        return NarrativeEnvelope(status="no_report")
    prompt = spec.copied_prompt(context)
    stored = spec.read_stored()
    if stored is None:
        return NarrativeEnvelope(status="prompt", prompt=prompt)
    return NarrativeEnvelope(
        status="ok", content=stored.prose, prompt=prompt, who=stored.model,
        when=stored.generated_at, cost_usd=stored.cost_usd,
        stale=stored.context_hash != spec.context_hash(context),
    )


def narrative_post(
    conn: sqlite3.Connection,
    spec: NarrativeSpec,
    *,
    write: Callable[[str, Completion, Any], None],
) -> NarrativeEnvelope:
    """``POST .../narrative``: write this route's evidence through
    ``llm.write_prose`` and store the answer. It sends ``spec.full_prompt``,
    never the copyable prompt: no answer contract, the reply is prose. The
    match-report and leak-finder routes vary only what evidence goes in and
    where the prose lands, both carried by ``spec`` and ``write``.
    """
    cfg = require_credential()
    context = spec.build_context()
    if context is None:
        raise HTTPException(status_code=404, detail=spec.no_context_detail)
    prompt = spec.full_prompt(context)
    try:
        completion = llm_client.write_prose(prompt, cfg=cfg, label=spec.label)
    except llm_client.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    run_authored_write(conn, lambda: write(prompt, completion, context))

    stored = spec.read_stored()
    assert stored is not None
    return NarrativeEnvelope(
        status="ok", content=stored.prose, prompt=prompt, who=stored.model,
        when=stored.generated_at, cost_usd=stored.cost_usd, stale=False,
    )
