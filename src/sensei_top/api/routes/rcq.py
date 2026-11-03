"""The RCQ guide's preview: the pasted 75 read back against the field.
Read-only and makes no call. The generate, paste, latest and Markdown routes
are ``ai/routes/rcq.py`` — ``/api/guide/{key}/rcq*`` (``docs/guide.md``).
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Protocol

from fastapi import APIRouter, HTTPException, Query, Request

from sensei_top.api.convert import _list_diff_out
from sensei_top.api.deps import Conn
from sensei_top.api.models.rcq import (
    RcqExpectedOut,
    RcqFreshnessOut,
    RcqPreviewOut,
    RcqRecentEventOut,
    RcqRecentShareOut,
)
from sensei_top.api.providers import providers_of
from sensei_top.api.sql import _shared_report_cache
from sensei_top.guide.decklist import parse_decklist
from sensei_top.guide.rcq import RcqEvidence, build_rcq, top8_name
from sensei_top.i18n import _, english

router = APIRouter()


class RcqPromptProvider(Protocol):
    """The copy-and-paste prompt for ``evidence`` (``ai/`` lends it)."""

    def __call__(self, evidence: RcqEvidence, *, conn: sqlite3.Connection) -> str: ...


def _key_by_name(conn: sqlite3.Connection) -> dict[str, str]:
    """Corpus archetype name -> key, the most common key per name."""
    rows = conn.execute(
        """
        SELECT archetype_name AS name, archetype_key AS key, COUNT(*) AS n
          FROM meta_deck_archetype WHERE archetype_key IS NOT NULL
         GROUP BY 1, 2 ORDER BY n ASC, key DESC
        """
    ).fetchall()
    # Ascending count, so the last write per name is the most common key.
    return {r["name"]: r["key"] for r in rows}


def _no_deck(key: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=_("No deck for key {key}.").format(key=repr(key)),
    )


def _preview(evidence: RcqEvidence, conn: sqlite3.Connection, prompt: str | None) -> RcqPreviewOut:
    """The page's fields in the request's language. ``evidence`` was built
    in English, for ``prompt``, so nothing here copies its text: each
    sentence is written now from the data behind it — the pasted text is
    parsed again (``parse_decklist`` is pure), and the unclassified reason,
    the duplicate warnings and the top-8 sentinel are formatted from
    codes."""
    keys = _key_by_name(conn)
    return RcqPreviewOut(
        format=evidence.guide.field.fmt,
        main_count=sum(evidence.parsed.main.values()),
        side_count=sum(evidence.parsed.side.values()),
        warnings=list(parse_decklist(evidence.decklist_text).warnings),
        unresolved=list(evidence.resolved.unresolved),
        own_archetype_key=evidence.own_verdict_key,
        own_archetype_name=evidence.own_verdict_name,
        own_unclassified_reason=evidence.own_unclassified_reason,
        list_diff=_list_diff_out(evidence.list_diff),
        recent_shares=[
            RcqRecentShareOut(
                archetype=s.archetype, archetype_key=keys.get(s.archetype),
                share=s.share, decks=s.decks,
            )
            for s in evidence.recent_shares
        ],
        recent_events=[
            RcqRecentEventOut(
                date=e.date, name=e.name, source=e.source, tier=e.tier,
                decks=e.decks, top8=[top8_name(name) for name in e.top8],
            )
            for e in evidence.recent_events
        ],
        freshness=[
            RcqFreshnessOut(
                source=f.source, newest_event=f.newest_event, fetched_at=f.fetched_at
            )
            for f in evidence.freshness
        ],
        expected=[
            RcqExpectedOut(
                key=x.key, name=x.name, share=x.share,
                wins=x.record.wins if x.record else None,
                losses=x.record.losses if x.record else None,
                carryable=x.record.carryable if x.record else None,
            )
            for x in evidence.expected
        ],
        prompt=prompt,
    )


@router.get("/api/guide/{key}/rcq/preview", response_model=RcqPreviewOut, tags=["guide"])
def rcq_preview(
    key: str,
    request: Request,
    conn: Conn,
    decklist: str = "",
    expected: Annotated[list[str] | None, Query()] = None,
    own: str | None = None,
) -> RcqPreviewOut:
    """The pasted 75 read back against the field, and the prompt that would
    be sent when ``ai/`` lends one (``api/providers.py``), else ``null``.
    Read-only; makes no call. 404 is an unknown deck."""
    # One English build serves the prompt and the page (see _preview).
    with english():
        evidence = build_rcq(
            conn, key, decklist, list(expected or []), own,
            report_cache=_shared_report_cache(request, conn),
        )
        provider = providers_of(request.app).rcq_prompt
        prompt = provider(evidence, conn=conn) if evidence and provider else None
    if evidence is None:
        raise _no_deck(key)
    return _preview(evidence, conn, prompt)
