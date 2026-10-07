"""The deck guide's whole evidence bundle, its authored narrative, the
evidence-only markdown export, and its cached matchup briefs —
``/api/guide/*`` (``docs/guide.md``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from sensei_top.api.convert import (
    _coverage_out,
    _deck_guide_out,
    _deck_identity_out,
    _guide_narrative_out,
    _matchup_brief_out,
)
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.common import MatchupBriefOut
from sensei_top.api.models.guide import (
    BriefPromptOut,
    CoverageOut,
    CoveragePromptOut,
    DeckGuideOut,
    DeckIdentityOut,
    GuideMarkdownOut,
    GuideNarrativeResponse,
)
from sensei_top.api.routes.narrative import require_credential, run_authored_write
from sensei_top.api.sql import _shared_report_cache
from sensei_top.brief.coverage import build_coverage
from sensei_top.brief.store import briefs_for_deck, corpus_commit, list_hash
from sensei_top.guide import narrative as guide_narrative
from sensei_top.guide.bundle import build_deck_guide
from sensei_top.guide.deck import identity_format, list_identities, resolve
from sensei_top.guide.markdown import render as render_guide_markdown
from sensei_top.llm import client as llm_client

router = APIRouter()


@router.get("/api/guide/decks", response_model=list[DeckIdentityOut], tags=["guide"])
def guide_decks(conn: Conn) -> list[DeckIdentityOut]:
    """Every deck with recorded matches, one row per Arena GUID
    (``guide/deck.py``) — the picker behind the deck guide. Newest
    played first, same ordering ``list_identities`` returns.
    """
    return [_deck_identity_out(identity) for identity in list_identities(conn)]


@router.get("/api/guide/{key}", response_model=DeckGuideOut, tags=["guide"])
def guide(key: str, request: Request, conn: Conn) -> DeckGuideOut:
    """One deck's whole evidence bundle: play patterns, this deck's own
    leak-finder rollup beside every deck's, the current 75 against the
    field's consensus, and the field itself around any detected format
    reset — see ``guide/bundle.py``. 404 mirrors ``match_report``'s own
    posture: a key that resolves to nothing is a missing resource.
    """
    deck_guide = build_deck_guide(conn, key, report_cache=_shared_report_cache(request, conn))
    if deck_guide is None:
        raise HTTPException(status_code=404, detail=f"No deck for key {key!r}.")
    return _deck_guide_out(deck_guide)


@router.get(
    "/api/guide/{key}/narrative", response_model=GuideNarrativeResponse, tags=["guide"]
)
def guide_narrative_route(key: str, request: Request, conn: Conn) -> GuideNarrativeResponse:
    """The deck's stored narrative, and always the prompt to (re)write it
    from.

    ``status`` is ``'ok'`` when a narrative has been generated (``POST``
    on this same path) or imported (``sensei-top guide --deck KEY
    --import FILE``) for this deck, and ``'prompt'`` when none has —
    either way ``prompt`` carries the text to write one from, so the tab
    can offer "write it" and "rewrite it" with the same affordance.

    ``stale`` compares the stored ``list_hash`` against the deck's
    current 75: a narrative written for a different 75 names cards the
    deck may no longer hold, which is worth flagging loudly rather than
    rendering as current.
    """
    from sensei_top.guide.authored import narrative_for

    deck_guide = build_deck_guide(conn, key, report_cache=_shared_report_cache(request, conn))
    if deck_guide is None:
        raise HTTPException(status_code=404, detail=f"No deck for key {key!r}.")

    prompt = guide_narrative.full_prompt(deck_guide, conn=conn)
    if prompt is None:
        return GuideNarrativeResponse(status="no_report")

    stored = narrative_for(conn, deck_guide.provenance.deck.key)
    if stored is None:
        return GuideNarrativeResponse(status="prompt", prompt=prompt)

    authored, narrative = stored
    return GuideNarrativeResponse(
        status="ok",
        guide=_guide_narrative_out(narrative),
        prompt=prompt,
        authored_at=authored.authored_at,
        author=authored.author,
        cost_usd=authored.cost_usd,
        stale=authored.list_hash != list_hash(deck_guide.provenance.deck.current_cards),
    )


@router.post(
    "/api/guide/{key}/narrative", response_model=GuideNarrativeResponse, tags=["guide"]
)
def generate_guide_narrative(
    key: str, request: Request, conn: WritableConn
) -> GuideNarrativeResponse:
    """Write this deck's guide narrative with Claude, and store it.

    Sends the same ``full_prompt`` the copy-prompt path has always
    served, but requests the answer via structured outputs against
    ``_GUIDE_TOOL``'s own schema — the same shape ``sensei-top guide
    --import`` already parses (``guide_narrative_from_json``), so the
    generate path and the hand-import path converge on one validator.
    Also fills every matchup plan the guide covers into
    ``matchup_brief``, exactly like the CLI import
    (``brief/from_guide.py``) — this is the whole reason the live
    matchup brief needs no generate button of its own.
    """
    from sensei_top.brief.from_guide import store_guide_matchups
    from sensei_top.guide.authored import narrative_for, write_narrative
    from sensei_top.guide.narrative import (
        _GUIDE_TOOL,
        NarrativeError,
        guide_narrative_from_json,
    )

    deck_guide = build_deck_guide(conn, key, report_cache=_shared_report_cache(request, conn))
    if deck_guide is None:
        raise HTTPException(status_code=404, detail=f"No deck for key {key!r}.")

    cfg = require_credential()

    prompt = guide_narrative.full_prompt(deck_guide, conn=conn)
    if prompt is None:
        raise HTTPException(
            status_code=404, detail="Nothing to write about for this deck yet."
        )

    schema = llm_client.strict_schema(_GUIDE_TOOL["input_schema"])
    try:
        completion = llm_client.write_json(prompt, schema, cfg=cfg, label="deck guide")
    except llm_client.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        narrative = guide_narrative_from_json(completion.text, deck_guide)
    except NarrativeError as exc:
        raise HTTPException(
            status_code=502, detail=f"Claude's answer could not be read: {exc}"
        ) from exc

    identity = deck_guide.provenance.deck
    # One transaction, not two: this route is the only writer that touches a
    # second table (`matchup_brief`, via `store_guide_matchups`). A guide
    # stored without its matchup briefs would render as a guide whose
    # matchup section silently lost its plans, and the next request would
    # read it as complete rather than retrying.
    def write() -> None:
        write_narrative(
            conn, identity.key, narrative,
            list_hash=list_hash(identity.current_cards),
            prompt=prompt,
            author=completion.model,
            corpus_commit=corpus_commit(conn),
            input_tokens=completion.input_tokens, output_tokens=completion.output_tokens,
            cost_usd=completion.cost_usd,
        )
        store_guide_matchups(conn, deck_guide, narrative, model=completion.model)

    run_authored_write(conn, write)

    stored = narrative_for(conn, identity.key)
    assert stored is not None
    authored, stored_narrative = stored
    return GuideNarrativeResponse(
        status="ok",
        guide=_guide_narrative_out(stored_narrative),
        prompt=prompt,
        authored_at=authored.authored_at,
        author=authored.author,
        cost_usd=authored.cost_usd,
        stale=False,
    )


@router.get("/api/guide/{key}/markdown", response_model=GuideMarkdownOut, tags=["guide"])
def guide_markdown(key: str, request: Request, conn: Conn) -> GuideMarkdownOut:
    """The evidence-only guide document — ``guide/markdown.py``'s
    ``render`` with no narrative, exported for copy or save. The
    narrative sections (engine, matchups, checklist) are generated
    client-side by the narrative route and are not included here: this
    route makes no Claude call, so it can never carry text that call
    alone produces.
    """
    deck_guide = build_deck_guide(conn, key, report_cache=_shared_report_cache(request, conn))
    if deck_guide is None:
        raise HTTPException(status_code=404, detail=f"No deck for key {key!r}.")
    return GuideMarkdownOut(markdown=render_guide_markdown(deck_guide))


@router.get("/api/guide/{key}/briefs", response_model=list[MatchupBriefOut], tags=["guide"])
def guide_briefs(key: str, conn: Conn) -> list[MatchupBriefOut]:
    """Every live matchup brief cached for this deck — see
    ``brief/__init__.py``. Empty rather than 404 for a deck key that
    resolves to nothing here: the guide route is the one that owns
    "no such deck", and a brief list is naturally empty for a deck
    that has never faced a classified opponent yet.
    """
    return [_matchup_brief_out(b) for b in briefs_for_deck(conn, key)]


@router.get("/api/guide/{key}/coverage", response_model=CoverageOut, tags=["guide"])
def guide_coverage(key: str, conn: Conn) -> CoverageOut:
    """How well this deck's cached matchup briefs cover the archetypes it
    actually faces and the field's own top archetypes — see
    ``brief/coverage.py``. 404 mirrors the other guide routes: a key that
    resolves to nothing is a missing resource.
    """
    identity = resolve(conn, key)
    if identity is None:
        raise HTTPException(status_code=404, detail=f"No deck for key {key!r}.")
    return _coverage_out(build_coverage(conn, identity))


@router.get(
    "/api/guide/{key}/briefs/{archetype_key}/prompt",
    response_model=BriefPromptOut, tags=["guide"],
)
def guide_brief_prompt(key: str, archetype_key: str, conn: Conn) -> BriefPromptOut:
    """The single-brief prompt for one archetype — the same text
    ``sensei-top brief --deck KEY --archetype KEY --prompt`` prints,
    fetched only when the coverage card's own "copy prompt" action is
    clicked rather than for every row up front. ``status`` is
    ``'format_unknown'`` when the deck has no format (checked first), and
    ``'no_consensus'`` rather than an error code when the archetype has no
    field consensus yet — an ordinary outcome for a young corpus, same
    posture as ``MatchupBriefResponse``; the deck key is what 404s here,
    not the archetype.
    """
    from sensei_top.brief.narrative import full_prompt

    identity = resolve(conn, key)
    if identity is None:
        raise HTTPException(status_code=404, detail=f"No deck for key {key!r}.")
    if identity_format(conn, identity) is None:
        # No format, no field to read a consensus from: not a thin corpus.
        return BriefPromptOut(status="format_unknown", archetype_key=archetype_key)

    coverage = build_coverage(conn, identity)
    label = next(
        (row.label for row in coverage.rows if row.archetype_key == archetype_key),
        archetype_key,
    )
    built = full_prompt(conn, identity, archetype_key, label)
    if built is None:
        return BriefPromptOut(status="no_consensus", archetype_key=archetype_key)
    prompt, _facts = built
    return BriefPromptOut(status="ok", archetype_key=archetype_key, prompt=prompt)


@router.get(
    "/api/guide/{key}/coverage/prompt", response_model=CoveragePromptOut, tags=["guide"],
)
def guide_coverage_prompt(key: str, conn: Conn) -> CoveragePromptOut:
    """The multi-brief prompt for every archetype this deck's coverage
    marks ``missing``/``stale`` — the same text
    ``sensei-top brief --deck KEY --missing --prompt`` prints, built in
    coverage order (times faced desc, then field share desc, then key) so
    the busiest gaps are never the ones ``MULTI_BRIEF_MAX`` defers. A
    separate path from ``/briefs/{archetype_key}/prompt`` (not nested
    under it) so an archetype key can never collide with the literal
    ``coverage`` segment.

    ``status`` is ``'format_unknown'`` when the deck has no format (checked
    first: there is no field, so nothing to be missing or lack consensus),
    ``'nothing_missing'`` when every row is already ``ok``,
    and ``'no_consensus'`` when ``full_multi_prompt`` found consensus for
    none of the missing/stale archetypes (it returns ``None`` rather than
    naming which ones in that all-or-nothing case, so every missing/stale
    key is reported under ``no_consensus`` here rather than guessing —
    the same coarse message ``brief --missing --prompt`` itself gives).
    """
    from sensei_top.brief.narrative import full_multi_prompt

    identity = resolve(conn, key)
    if identity is None:
        raise HTTPException(status_code=404, detail=f"No deck for key {key!r}.")
    if identity_format(conn, identity) is None:
        return CoveragePromptOut(
            status="format_unknown", included=[], no_consensus=[], deferred=[],
        )

    coverage = build_coverage(conn, identity)
    gap_rows = [row for row in coverage.rows if row.status in ("missing", "stale")]
    archetypes = [(row.archetype_key, row.label) for row in gap_rows]

    if not archetypes:
        return CoveragePromptOut(
            status="nothing_missing", included=[], no_consensus=[], deferred=[],
        )

    built = full_multi_prompt(conn, identity, archetypes)
    if built is None:
        return CoveragePromptOut(
            status="no_consensus", included=[],
            no_consensus=[key for key, _ in archetypes], deferred=[],
        )
    return CoveragePromptOut(
        status="ok", prompt=built.prompt, included=list(built.included),
        no_consensus=list(built.no_consensus), deferred=list(built.deferred),
    )
