"""Shared plumbing for the three ``GET``/``POST .../narrative`` route pairs
(match report, leak finder, deck guide — ``docs/llm.md``).

The match report and the leak finder are the exact same shape end to end:
build some evidence, wrap it in a prompt, and — on ``POST`` with a
credential configured — send it through ``llm.write_prose`` and store the
prose verbatim. ``NarrativeSpec`` plus ``narrative_get``/``narrative_post``
below cover both in full; ``api/app.py`` supplies only the per-route
closures (which evidence, which store) as callables.

The deck guide is the JSON-schema-answer relative: its ``full_prompt``
returns the finished prompt directly rather than a separate context object,
its ``POST`` parses a structured answer instead of storing prose verbatim,
and it writes a second table (``matchup_brief``) in the same transaction.
Forcing it through ``NarrativeSpec`` would cost more in indirection than it
saves, so only what is genuinely identical across all three routes —
``require_credential``'s 503 and ``run_authored_write``'s transaction — is
shared with it too.

**Why no response model lives here**: ``NarrativeResponse`` and
``GuideNarrativeResponse`` stay defined in ``api/app.py`` (Step 5 of the
architecture-remediation plan relocates them). Importing either here would
make this module depend on ``app.py``, which already depends on this one —
so these functions return a ``NarrativeEnvelope`` instead, and each route in
``app.py`` builds its own response model from it.

**Why this module reaches into ``sensei_top.llm`` directly rather than
taking it as a parameter**: ``tests/test_llm.py`` monkeypatches
``sensei_top.api.app.llm_config.load`` and
``sensei_top.api.app.llm_client.write_prose``/``write_json`` — but those
names are the *same module objects* this file imports under the same
aliases, so a patch made through ``app.py``'s reference is visible here too.
Only functions ``app.py`` imports *by name* (``build_match_report``,
``find_leaks``, and the like) have to stay called from ``app.py``'s own
closures, since patching ``app_module.build_match_report`` cannot reach a
separate name binding in a different module.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

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


@dataclass(frozen=True, slots=True)
class NarrativeEnvelope:
    """What both response shapes (``NarrativeResponse``'s prose,
    ``GuideNarrativeResponse``'s structured guide) get built from.
    ``who``/``when`` are ``model``/``generated_at`` for a prose narrative or
    ``author``/``authored_at`` for the guide — the caller maps them onto
    whichever field names its own response model uses."""

    status: str
    content: Any = None
    prompt: str | None = None
    who: str | None = None
    when: str | None = None
    cost_usd: float | None = None
    stale: bool = False


def require_credential() -> LLMConfig:
    """The identical 503 all three ``POST .../narrative`` routes raise with
    nothing configured —
    ``tests/test_llm.py::test_no_credential_means_no_client_is_constructed``
    pins both the status code and this exact detail string."""
    cfg = llm_config.load()
    if cfg is None:
        raise HTTPException(status_code=503, detail=no_credential_detail())
    return cfg


def run_authored_write(conn: sqlite3.Connection, write: Callable[[], None]) -> None:
    """The ``BEGIN``/``COMMIT``/``ROLLBACK`` wrapper every ``POST
    .../narrative`` route uses — added in Step 1 because ``get_writable_conn``
    opens in autocommit mode, where a bare ``conn.commit()`` is a no-op on a
    write that already landed (see ``api/app.py``'s ``get_writable_conn``).
    Takes a callback rather than one hardcoded statement because the guide
    route's own write touches two tables (``deck_narrative`` and
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
    finder) needs beyond the shared control flow below. Built fresh per
    request by a small helper in ``app.py`` that closes over that request's
    own ``conn`` and path params, so this stays a plain function rather than
    a FastAPI dependency.
    """

    build_context: Callable[[], Any]
    full_prompt: Callable[[Any], str]
    read_stored: Callable[[], Any]
    context_hash: Callable[[Any], str]
    no_context_detail: str
    label: str


def narrative_get(spec: NarrativeSpec) -> NarrativeEnvelope:
    """``GET .../narrative``: the stored prose plus the prompt to (re)write
    it from, always a 200 — 'nothing to narrate' and 'nothing stored yet'
    are both ordinary outcomes for an opt-in feature, never errors."""
    context = spec.build_context()
    if context is None:
        return NarrativeEnvelope(status="no_report")
    prompt = spec.full_prompt(context)
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
    ``llm.write_prose`` and store the answer. Shared verbatim by the
    match-report and leak-finder routes — neither varies the call itself,
    only what evidence goes in and where the prose lands, both carried by
    ``spec`` and ``write``.
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
