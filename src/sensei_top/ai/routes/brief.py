"""The matchup brief's routes: the briefs and their coverage per deck, the
prompts and paste routes behind the brief and coverage cards —
``/api/guide/{key}/briefs*``, ``/api/guide/{key}/coverage*`` — and the live
brief for the match in progress, ``/api/current-match/brief``
(``docs/brief.md``)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from sensei_top.ai.answers import PASTED_AUTHOR, brief_for, coverage_for
from sensei_top.ai.brief.coverage import Coverage, build_coverage
from sensei_top.ai.brief.importer import import_brief, import_briefs
from sensei_top.ai.brief.narrative import NarrativeError, full_multi_prompt, full_prompt
from sensei_top.ai.brief.store import briefs_for_deck, is_stale, list_hash, read_brief
from sensei_top.ai.routes.narrative import (
    check_pasted_length,
    read_pasted,
    run_authored_write,
    unreadable_answer,
)
from sensei_top.api.convert import _matchup_brief_out
from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.common import (
    MatchupBriefOut,
    MatchupBriefResponse,
    PastedAnswerIn,
)
from sensei_top.api.models.guide import (
    BriefPromptOut,
    CoverageOut,
    CoveragePromptOut,
    CoverageRowOut,
)
from sensei_top.api.routes.guide import _no_deck
from sensei_top.api.sql import _cached_match_opponent
from sensei_top.guide.deck import identity_format, list_identities, resolve
from sensei_top.i18n import _, english

router = APIRouter()


def _coverage_out(coverage: Coverage) -> CoverageOut:
    return CoverageOut(
        fmt=coverage.fmt,
        rows=[
            CoverageRowOut(
                archetype_key=row.archetype_key, label=row.label, times_faced=row.times_faced,
                field_share=row.field_share, status=row.status,
            )
            for row in coverage.rows
        ],
        matches_covered=coverage.matches_covered,
        matches_covered_numerator=coverage.matches_covered_numerator,
        matches_covered_denominator=coverage.matches_covered_denominator,
        field_covered=coverage.field_covered,
    )


def _no_format() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=_(
            "This deck's format is not known yet, so there is no field to anchor "
            "a brief to."
        ),
    )


@router.get("/api/guide/{key}/briefs", response_model=list[MatchupBriefOut], tags=["guide"])
def guide_briefs(key: str, conn: Conn) -> list[MatchupBriefOut]:
    """Every live matchup brief cached for this deck — see
    ``ai/brief/__init__.py``. Empty rather than 404 for a deck key that
    resolves to nothing here: the guide route is the one that owns
    "no such deck", and a brief list is naturally empty for a deck
    that has never faced a classified opponent yet.
    """
    return [_matchup_brief_out(b) for b in briefs_for_deck(conn, key)]


@router.get("/api/guide/{key}/coverage", response_model=CoverageOut, tags=["guide"])
def guide_coverage(key: str, conn: Conn) -> CoverageOut:
    """How well this deck's cached matchup briefs cover the archetypes it
    actually faces and the field's own top archetypes — see
    ``ai/brief/coverage.py``. 404 mirrors the other guide routes: a key that
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
    """The single-brief prompt for one archetype, fetched only when the
    coverage card's own "copy prompt" action is clicked rather than for
    every row up front. ``status`` is
    ``'format_unknown'`` when the deck has no format (checked first), and
    ``'no_consensus'`` rather than an error code when the archetype has no
    field consensus yet — an ordinary outcome for a young corpus, same
    posture as ``MatchupBriefResponse``; the deck key is what 404s here,
    not the archetype.
    """
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
    marks ``missing``/``stale``, built in
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
    key is reported under ``no_consensus`` here rather than guessing).
    """
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
    """Store an answer pasted into one matchup brief's card. Makes no model
    call.

    Same refusals as the guide's: 422 for another card's or an unreadable
    answer (nothing stored), 413 over 256 KB. 409 when
    the deck has no format, or the archetype has no field
    consensus to anchor the brief to (a keyed sentence for each). A sideboard
    plan that does not balance is stored with the problem recorded. Stored with the
    ``context`` hash the answer carries and the sentinel author ``pasted``.
    """
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
    in it. Makes no model call. Returns what ``GET`` on this path returns.

    422 and 413 as for one brief; the batch is all-or-nothing on its JSON.
    An archetype with no field consensus is skipped, and the
    row stays ``no_consensus``; 409 only when nothing could be stored
    because no item had a field consensus; 409 as well for a deck with no
    format.
    """
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


def _brief_response(
    conn: Conn, request: Request, match_id: str, deck_id: str
) -> MatchupBriefResponse:
    """The body of ``GET /api/current-match/brief``. Not shared with
    ``current_match_read``'s own ``intermission`` field: that field is built
    from a name set that pools the live replay's own revealed zones with
    ``card_events`` (``table/intermission.py``), which can know more about
    the opponent mid-break than this route's ``_cached_match_opponent`` (a
    projection-only read) does — sharing this function there would silently
    cap the break read's opponent knowledge at whatever ``project()`` last
    saw.
    """
    identity = next((i for i in list_identities(conn) if deck_id in i.deck_ids), None)
    if identity is None:
        return MatchupBriefResponse(status="no_match")
    no_format = identity_format(conn, identity) is None
    opp_row = _cached_match_opponent(request, conn, match_id)
    opponent_key = opp_row["opponent_key"] if opp_row else None
    if not opponent_key or not opponent_key.startswith("archetype:"):
        # Before ``unclassified``: the classifier never names an opponent in
        # a match with no format, so "unclassified" would promise a read that
        # never comes.
        return MatchupBriefResponse(
            status="format_unknown" if no_format else "unclassified"
        )
    archetype_key = opponent_key.removeprefix("archetype:")
    archetype_label = opp_row["opponent_label"]

    if no_format:
        # A brief stored while the deck had a format is still the user's:
        # returned first, with no prompt (none can be built without a
        # format). Only when nothing is stored is the format the answer.
        stored = read_brief(conn, identity.key, archetype_key)
        if stored is None:
            return MatchupBriefResponse(status="format_unknown")
        return MatchupBriefResponse(
            status="ok", brief=_matchup_brief_out(stored),
            deck_key=identity.key, archetype_key=archetype_key,
            stale=is_stale(
                conn, stored, current_list_hash=list_hash(identity.current_cards)
            ),
        )

    built = full_prompt(conn, identity, archetype_key, archetype_label)
    if built is None:
        # No field consensus for this archetype: there is nothing to
        # anchor a brief to, and saying so is more honest than offering
        # a prompt that would be written from nothing.
        return MatchupBriefResponse(status="no_consensus")
    prompt = built[0]

    brief = read_brief(conn, identity.key, archetype_key)
    if brief is None:
        return MatchupBriefResponse(
            status="prompt", prompt=prompt,
            deck_key=identity.key, archetype_key=archetype_key,
        )

    return MatchupBriefResponse(
        status="ok", brief=_matchup_brief_out(brief), prompt=prompt,
        deck_key=identity.key, archetype_key=archetype_key,
        stale=is_stale(
            conn, brief, current_list_hash=list_hash(identity.current_cards)
        ),
    )


@router.get("/api/current-match/brief", response_model=MatchupBriefResponse, tags=["matches"])
def current_match_brief(request: Request, conn: Conn) -> MatchupBriefResponse:
    """The stored matchup brief for the match in progress, and the prompt
    to write one from — except an ``ok`` with no format, which has none (a
    prompt needs a format to name its corpus). See ``ai/brief/__init__.py`` and
    ``docs/brief.md``.

    Deliberately has no generate route of its own, unlike the match
    report and the deck guide (``docs/llm.md``): a brief is pasted into its
    card (``PUT /api/guide/{key}/briefs/{archetype_key}``) or the coverage
    card (``PUT /api/guide/{key}/coverage``), or — far more often — filled as a side effect of
    generating, pasting or importing a full deck guide
    (``POST``/``PUT /api/guide/{key}/narrative``, ``ai/brief/from_guide.py``).
    """
    match_row = conn.execute("SELECT match_id, deck_id FROM v_current_match").fetchone()
    if match_row is None or match_row["deck_id"] is None:
        return MatchupBriefResponse(status="no_match")
    return _brief_response(conn, request, match_row["match_id"], match_row["deck_id"])
