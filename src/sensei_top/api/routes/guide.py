"""The deck guide's whole evidence bundle, the evidence-only markdown
export, its cached matchup briefs and their coverage, with the prompts and
paste routes behind the brief and coverage cards — ``/api/guide/*`` (``docs/guide.md``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from sensei_top.ai.answers import PASTED_AUTHOR, brief_for, coverage_for
from sensei_top.ai.routes.narrative import (
    check_pasted_length,
    read_pasted,
    run_authored_write,
    unreadable_answer,
)
from sensei_top.api.convert import (
    _coverage_out,
    _deck_guide_out,
    _deck_identity_out,
    _matchup_brief_out,
)
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.common import MatchupBriefOut, PastedAnswerIn
from sensei_top.api.models.guide import (
    BriefPromptOut,
    CoverageOut,
    CoveragePromptOut,
    DeckGuideOut,
    DeckIdentityOut,
    GuideMarkdownOut,
)
from sensei_top.api.sql import _shared_report_cache
from sensei_top.brief.coverage import build_coverage
from sensei_top.brief.store import briefs_for_deck
from sensei_top.guide.bundle import build_deck_guide
from sensei_top.guide.deck import identity_format, list_identities, resolve
from sensei_top.guide.markdown import render as render_guide_markdown
from sensei_top.i18n import _, english

router = APIRouter()


def _no_deck(key: str) -> HTTPException:
    return HTTPException(
        status_code=404, detail=_("No deck for key {key}.").format(key=repr(key)),
    )


def _no_format() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=_(
            "This deck's format is not known yet, so there is no field to anchor "
            "a brief to."
        ),
    )


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
        raise _no_deck(key)
    return _deck_guide_out(deck_guide)


@router.get("/api/guide/{key}/markdown", response_model=GuideMarkdownOut, tags=["guide"])
def guide_markdown(key: str, request: Request, conn: Conn) -> GuideMarkdownOut:
    """The evidence-only guide document — ``guide/markdown.py``'s
    ``render`` with no narrative, exported for copy or save. The
    narrative sections (engine, matchups, checklist) come from the
    narrative route and are not included here: this
    route makes no Claude call, so it can never carry text that call
    alone produces.
    """
    # English, like every prompt: the export is prompt input, and the guide
    # it renders is built here, so the whole build is in scope.
    with english():
        deck_guide = build_deck_guide(
            conn, key, report_cache=_shared_report_cache(request, conn),
        )
        markdown = render_guide_markdown(deck_guide) if deck_guide is not None else None
    if markdown is None:
        raise _no_deck(key)
    return GuideMarkdownOut(markdown=markdown)


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
        raise _no_deck(key)
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
        raise _no_deck(key)
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
        raise _no_deck(key)
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
            no_consensus=[key for key, _label in archetypes], deferred=[],
        )
    return CoveragePromptOut(
        status="ok", prompt=built.prompt, included=list(built.included),
        no_consensus=list(built.no_consensus), deferred=list(built.deferred),
    )


@router.put(
    "/api/guide/{key}/briefs/{archetype_key}", response_model=MatchupBriefOut, tags=["guide"],
)
def paste_brief(
    key: str, archetype_key: str, body: PastedAnswerIn, conn: WritableConn
) -> MatchupBriefOut:
    """Store an answer pasted into one matchup brief's card — what
    ``sensei-top brief --deck KEY --archetype KEY --import FILE`` stores.
    Makes no model call.

    Same refusals as the guide's: 422 for another card's or an unreadable
    answer (nothing stored), 413 over 256 KB. 409 where the CLI stops with a
    ``LookupError``: the deck has no format, or the archetype has no field
    consensus to anchor the brief to (a keyed sentence for each). A sideboard
    plan that does not balance is stored with the problem recorded, as on the CLI. Stored with the
    ``context`` hash the answer carries and the sentinel author ``pasted``.
    """
    from sensei_top.brief.importer import import_brief
    from sensei_top.brief.narrative import NarrativeError

    check_pasted_length(body.answer)
    identity = resolve(conn, key)
    if identity is None:
        raise _no_deck(key)
    answer = read_pasted(body.answer, brief_for(identity.key, archetype_key))

    if identity_format(conn, identity) is None:
        raise _no_format()
    label = next(
        (r.label for r in build_coverage(conn, identity).rows
         if r.archetype_key == archetype_key),
        None,
    ) or archetype_key
    stored: list = []
    try:
        with english():
            run_authored_write(
                conn,
                lambda: stored.append(import_brief(
                    conn, identity, archetype_key, label, answer.body,
                    author=PASTED_AUTHOR, written_for=answer.context,
                )),
            )
    except NarrativeError as exc:
        raise unreadable_answer(exc) from exc
    except LookupError as exc:
        # The format is known (checked above), so this is the importer's
        # other refusal: no field consensus for the archetype.
        raise HTTPException(
            status_code=409,
            detail=_(
                "The field has no consensus list for {archetype} yet, so there is "
                "nothing to anchor a brief to."
            ).format(archetype=label),
        ) from exc
    return _matchup_brief_out(stored[0])


@router.put("/api/guide/{key}/coverage", response_model=CoverageOut, tags=["guide"])
def paste_coverage(key: str, body: PastedAnswerIn, conn: WritableConn) -> CoverageOut:
    """Store the answer pasted into the matchup-coverage card — every brief
    in it, what ``sensei-top brief --deck KEY --missing --import FILE``
    stores. Makes no model call. Returns what ``GET`` on this path returns.

    422 and 413 as for one brief; the batch is all-or-nothing on its JSON.
    An archetype with no field consensus is skipped, as on the CLI, and the
    row stays ``no_consensus``; 409 only when nothing could be stored
    because no item had a field consensus; 409 as well for a deck with no
    format.
    """
    from sensei_top.brief.importer import import_briefs
    from sensei_top.brief.narrative import NarrativeError

    check_pasted_length(body.answer)
    identity = resolve(conn, key)
    if identity is None:
        raise _no_deck(key)
    answer = read_pasted(body.answer, coverage_for(identity.key))

    if identity_format(conn, identity) is None:
        raise _no_format()
    labels = {r.archetype_key: r.label for r in build_coverage(conn, identity).rows}
    result: list = []
    try:
        with english():
            run_authored_write(
                conn,
                lambda: result.append(import_briefs(
                    conn, identity, answer.body, author=PASTED_AUTHOR, labels=labels,
                    written_for=answer.context,
                )),
            )
    except NarrativeError as exc:
        raise unreadable_answer(exc) from exc
    stored, skipped = result[0]
    if not stored and skipped:
        raise HTTPException(
            status_code=409,
            detail=_(
                "The field has no consensus list yet for any archetype in this answer, "
                "so none of its briefs could be stored."
            ),
        )
    return _coverage_out(build_coverage(conn, identity))
