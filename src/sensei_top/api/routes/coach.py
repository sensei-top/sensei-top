"""The coach: a dated, cross-deck report over every completed Arena/MTGO
constructed match — ``/api/coach*`` (``docs/coach.md``).

``GET /api/coach`` is free and local — the evidence for the tab's own
profile tables, plus every report ever written. The three
``.../narrative`` routes are shaped like ``api/routes/narrative.py``'s
three pairs, but this one can't reuse ``narrative_get``/``narrative_post``:
those are hardwired to a single current row (``write_prose`` plus one
stored slot a regenerate overwrites), while a coach report is history
(``coach/store.py``'s own module docstring) and its ``POST`` calls
``llm.write_report`` — the web-search entry point, not ``write_prose`` —
and resolves its credential through ``load_coach()`` rather than
``load()``. What *is* shared: ``NO_CREDENTIAL_DETAIL`` and
``run_authored_write``'s transaction wrapper. ``POST`` takes an optional
body picking the model from the Coach tab's dropdown (one of
``llm_client.REPORT_MODELS``); left out, it writes with the configured
coach model.

A report is for one format (plan 13, D12). ``GET /api/coach`` and the
latest-report and generate routes take an optional ``format`` query
parameter (``CoachFormatParam``, the same vocabulary as the metagame
routes' ``FormatParam`` with its own description); omitted,
they use ``api/sql.py::default_format`` (D13), and every response says
which format it used. The report list stays the whole history, every
format, each row naming its own.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from sensei_top.api.deps import Conn, WritableConn
from sensei_top.api.models.coach import (
    CoachEvidenceModel,
    CoachGenerateRequest,
    CoachModelOption,
    CoachNarrativeResponse,
    CoachReportSummary,
    CoachResponse,
    CoachSource,
    DeckLeaksOut,
    DeckLineOut,
    FieldLineOut,
    LeakLineOut,
    MatchupLineOut,
    RateModel,
    TurningBucketOut,
)
from sensei_top.api.models.metagame import FormatName
from sensei_top.api.routes.narrative import NO_CREDENTIAL_DETAIL, run_authored_write
from sensei_top.api.sql import _shared_report_cache, default_format
from sensei_top.coach.canon import ALLOWED_DOMAINS, CANON
from sensei_top.coach.evidence import (
    CoachEvidence,
    DeckLeaks,
    DeckLine,
    FieldLine,
    LeakLine,
    MatchupLine,
    Rate,
    TurningBucket,
    build_coach_evidence,
)
from sensei_top.coach.narrative import build_coach_prompt, cited_ids, clean_report, web_sources
from sensei_top.coach.store import (
    CoachReport,
    latest_coach_report,
    list_coach_reports,
    read_coach_report,
    write_coach_report,
)
from sensei_top.llm import client as llm_client
from sensei_top.llm import config as llm_config
from sensei_top.review.leaks import MIN_SAMPLE

router = APIRouter()
log = logging.getLogger(__name__)

CoachFormatParam = Annotated[
    FormatName | None,
    Query(
        alias="format",
        description="which format the report is for; omitted, the default /api/formats reports",
    ),
]

_READING_ID_RE = re.compile(r"^R(\d+)$")
_CANON_BY_ID = {entry.id: entry for entry in CANON}


def _rate_out(rate: Rate) -> RateModel:
    return RateModel(
        wins=rate.wins, n=rate.n, rate=rate.rate,
        ci_low=rate.ci[0], ci_high=rate.ci[1], anecdotal=rate.anecdotal,
    )


def _deck_line_out(d: DeckLine) -> DeckLineOut:
    return DeckLineOut(
        label=d.label, archetype=d.archetype, matches=_rate_out(d.matches),
        g1=_rate_out(d.g1), post_board=_rate_out(d.post_board),
        on_play=_rate_out(d.on_play), on_draw=_rate_out(d.on_draw),
    )


def _matchup_line_out(m: MatchupLine) -> MatchupLineOut:
    return MatchupLineOut(archetype=m.archetype, rate=_rate_out(m.rate), variants=list(m.variants))


def _leak_line_out(leak: LeakLine) -> LeakLineOut:
    return LeakLineOut(
        code=leak.code, category=leak.category, pattern=leak.pattern,
        present=_rate_out(leak.present), absent=_rate_out(leak.absent), gap=leak.gap,
    )


def _deck_leaks_out(dl: DeckLeaks) -> DeckLeaksOut:
    return DeckLeaksOut(
        deck_label=dl.deck_label, leaks=[_leak_line_out(leak) for leak in dl.leaks],
    )


def _turning_bucket_out(bucket: TurningBucket) -> TurningBucketOut:
    return TurningBucketOut(stage=bucket.stage, severity=bucket.severity, games=bucket.games)


def _field_line_out(f: FieldLine) -> FieldLineOut:
    return FieldLineOut(
        archetype=f.archetype, variants=list(f.variants), decks=f.decks,
        share=f.share, your_rate=_rate_out(f.your_rate),
    )


def _model_option_out(model_id: str, label: str) -> CoachModelOption:
    prices = llm_client.price_per_mtok(model_id)
    return CoachModelOption(
        id=model_id, label=label,
        input_per_mtok=prices[0] if prices is not None else None,
        output_per_mtok=prices[1] if prices is not None else None,
    )


def from_evidence(e: CoachEvidence) -> CoachEvidenceModel:
    """The explicit dataclass-to-wire-model conversion ``docs/frontend.md``'s
    contract calls for — never ``model_validate`` on a dataclass, which
    would silently start passing through a field the wire model was never
    meant to expose (``source``, ``format_population``, the prompt-only
    ``examples``/``decklists``)."""
    return CoachEvidenceModel(
        as_of=e.as_of, population=e.population, window_start=e.window_start,
        overall=_rate_out(e.overall), overall_games=_rate_out(e.overall_games),
        g1=_rate_out(e.g1), post_board=_rate_out(e.post_board),
        on_play=_rate_out(e.on_play), on_draw=_rate_out(e.on_draw),
        by_deck=[_deck_line_out(d) for d in e.by_deck],
        by_role={role: _rate_out(rate) for role, rate in e.by_role.items()},
        mulligans={key: _rate_out(rate) for key, rate in e.mulligans.items()},
        by_opponent=[_matchup_line_out(m) for m in e.by_opponent],
        leaks=[_leak_line_out(leak) for leak in e.leaks],
        deck_leaks=[_deck_leaks_out(dl) for dl in e.deck_leaks],
        turning_points=[_turning_bucket_out(b) for b in e.turning_points],
        field=[_field_line_out(f) for f in e.field],
        field_latest_event=e.field_latest_event,
        gaps=list(e.gaps),
    )


def _sources_out(sources: list, prose: str) -> list[CoachSource]:
    """A stored report's own ``sources_json`` (mixed: a bare reading id
    string, or a ``{url,title,cited_text}`` web-citation dict — the shape
    ``migrations/038_coach_report.sql`` documents), resolved into the
    dashboard's own contract, in that same order (stored web citations,
    then reading ids). Never raises on an entry it can't place: a reading
    id the current canon no longer carries, or a malformed item from some
    future writer, is dropped and logged at WARNING rather than failing the
    whole response — the rest of a report is still worth serving.

    Appended last: ``web_sources(prose)`` — the pages the report's own
    "## Sources" section named but ``sources_json`` never recorded, because
    the call returned no citation objects (``docs/coach.md``). Only an
    entry whose URL isn't already present above is added, so a report that
    *does* carry proper web citations one day doesn't get them doubled.
    """
    result: list[CoachSource] = []
    seen_urls: set[str] = set()
    for item in sources:
        if isinstance(item, str):
            match = _READING_ID_RE.match(item)
            entry = _CANON_BY_ID.get(int(match.group(1))) if match else None
            if entry is None:
                log.warning("coach report cited reading id %r; dropping unresolvable source", item)
                continue
            result.append(CoachSource(
                kind="reading", label=item, url=entry.url,
                title=f"{entry.author} — {entry.title}",
            ))
        elif isinstance(item, dict):
            url = item.get("url")
            if not isinstance(url, str) or not url:
                log.warning("coach report web source has no url; dropping: %r", item)
                continue
            raw_title = item.get("title")
            title = raw_title if isinstance(raw_title, str) else None
            raw_cited = item.get("cited_text")
            cited_text = raw_cited if isinstance(raw_cited, str) else None
            result.append(
                CoachSource(
                    kind="web", label=title or url, url=url, title=title, cited_text=cited_text
                )
            )
            seen_urls.add(url)
        else:
            log.warning("coach report source of type %s skipped: %r", type(item).__name__, item)

    for web in web_sources(prose):
        if web["url"] in seen_urls:
            continue
        seen_urls.add(web["url"])
        result.append(CoachSource(
            kind="web", label=web["title"] or web["url"], url=web["url"],
            title=web["title"], cited_text=web["cited_text"],
        ))
    return result


def _report_out(report: CoachReport, *, prompt: str | None, stale: bool) -> CoachNarrativeResponse:
    """The one conversion both GET routes and the POST route build their
    response from — see the module docstring for why this can't be
    ``narrative.narrative_get``/``narrative_post``'s ``NarrativeEnvelope``
    instead (a coach report carries fields — ``id``, ``effort``, token
    counts, resolved sources — that shape has no room for). ``clean_report``
    strips any narration a report's own call left before its first
    heading (1a) — stored prose stays verbatim, so this runs here, the one
    place all three routes pass their prose through.
    """
    return CoachNarrativeResponse(
        status="ok",
        format=report.format,
        id=report.id,
        narrative=clean_report(report.prose),
        prompt=prompt,
        model=report.model,
        effort=report.effort,
        generated_at=report.generated_at,
        cost_usd=report.cost_usd,
        input_tokens=report.input_tokens,
        output_tokens=report.output_tokens,
        web_search_requests=report.web_search_requests,
        sources=_sources_out(report.sources, report.prose),
        stale=stale,
    )


@router.get("/api/coach", response_model=CoachResponse, tags=["coach"])
def coach(request: Request, conn: Conn, fmt: CoachFormatParam = None) -> CoachResponse:
    """The Coach tab's free half: the cross-deck evidence for its profile
    tables, built for one format, and every report ever written, of every
    format. Always a 200 — a database below the leak finder's own minimum
    sample is an ordinary state for a new install, not a server error
    (``sufficient=False``, ``evidence=None``).
    """
    fmt = fmt or default_format(conn)
    evidence = build_coach_evidence(
        conn, fmt=fmt, source="all", report_cache=_shared_report_cache(request, conn),
    )
    reports = list_coach_reports(conn)
    cfg = llm_config.load_coach()
    return CoachResponse(
        format=fmt,
        sufficient=evidence is not None,
        evidence=from_evidence(evidence) if evidence is not None else None,
        reports=[
            CoachReportSummary(
                id=r.id, generated_at=r.generated_at, format=r.format, model=r.model,
                effort=r.effort, cost_usd=r.cost_usd,
                web_search_requests=r.web_search_requests,
            )
            for r in reports
        ],
        default_model=cfg.model if cfg is not None else None,
        models=[
            _model_option_out(model_id, label)
            for model_id, label in llm_client.REPORT_MODELS.items()
        ],
    )


@router.get("/api/coach/narrative", response_model=CoachNarrativeResponse, tags=["coach"])
def coach_narrative(
    request: Request, conn: Conn, fmt: CoachFormatParam = None
) -> CoachNarrativeResponse:
    """The latest stored report for one format plus that format's current
    prompt, and whether the two have drifted apart. Same three-state
    posture as every other ``GET .../narrative`` route: 'nothing to report
    on yet' and 'nothing written yet' are both ordinary outcomes for an
    opt-in feature. Only a report of the same format is ever the latest
    one here, so another format's report can never read as current.
    """
    fmt = fmt or default_format(conn)
    p = build_coach_prompt(conn, fmt=fmt, report_cache=_shared_report_cache(request, conn))
    latest = latest_coach_report(conn, fmt)
    if latest is not None:
        stale = p is not None and latest.context_hash != p.context_hash
        return _report_out(latest, prompt=p.prompt if p is not None else None, stale=stale)
    if p is not None:
        return CoachNarrativeResponse(status="prompt", format=fmt, prompt=p.prompt)
    return CoachNarrativeResponse(status="no_report", format=fmt)


@router.get(
    "/api/coach/narrative/{report_id}", response_model=CoachNarrativeResponse, tags=["coach"]
)
def coach_narrative_by_id(report_id: int, conn: Conn) -> CoachNarrativeResponse:
    """One past report exactly as it was written — its own stored prompt,
    never a freshly rebuilt one, and ``stale`` is always False: staleness
    only means something for the latest report, since an old report is
    expected to disagree with today's evidence."""
    report = read_coach_report(conn, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No coach report with id {report_id}.")
    return _report_out(report, prompt=report.prompt, stale=False)


@router.post("/api/coach/narrative", response_model=CoachNarrativeResponse, tags=["coach"])
def generate_coach_narrative(
    request: Request,
    conn: WritableConn,
    body: CoachGenerateRequest | None = None,
    fmt: CoachFormatParam = None,
) -> CoachNarrativeResponse:
    """Write a fresh coach report with Claude and store it as a new row —
    never an upsert, since "Since your last report" reads the previous
    row's own ``metrics_json`` (``coach/store.py``). The model comes from
    the Coach tab's dropdown (``body.model``, one of ``llm_client.
    REPORT_MODELS``) when given, else the configured coach model
    (``load_coach()``'s own ``[claude.coach]`` override or the base
    ``[claude]`` model). Mirrors ``narrative_post``'s exact order: a bad
    model id first (422, before touching config or building anything),
    then the credential (503), then evidence (404), then the call (502 on
    failure), then the write. The report is for ``fmt`` (the ``format``
    query parameter, else ``default_format``), stored with it.
    """
    if body is not None and body.model is not None and body.model not in llm_client.REPORT_MODELS:
        raise HTTPException(
            status_code=422,
            detail=f"model must be one of {', '.join(llm_client.REPORT_MODELS)}",
        )

    cfg = llm_config.load_coach()
    if cfg is None:
        raise HTTPException(status_code=503, detail=NO_CREDENTIAL_DETAIL)
    if body is not None and body.model is not None:
        cfg = dataclasses.replace(cfg, model=body.model)

    fmt = fmt or default_format(conn)
    p = build_coach_prompt(conn, fmt=fmt, report_cache=_shared_report_cache(request, conn))
    if p is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Not enough completed constructed matches yet — the coach needs at least "
                f"{MIN_SAMPLE}."
            ),
        )

    try:
        completion = llm_client.write_report(
            p.prompt, cfg=cfg, label="coach", allowed_domains=list(ALLOWED_DOMAINS),
        )
    except llm_client.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    sources: list[Any] = [
        {"url": c.url, "title": c.title, "cited_text": c.cited_text}
        for c in completion.citations
    ]
    sources.extend(cited_ids(completion.text, p.entries))

    new_id: list[int] = []

    def write() -> None:
        new_id.append(
            write_coach_report(
                conn,
                format=fmt,
                prose=completion.text, prompt=p.prompt, model=completion.model,
                effort=cfg.effort, sources=sources, metrics=p.metrics,
                context_hash=p.context_hash, input_tokens=completion.input_tokens,
                output_tokens=completion.output_tokens,
                web_search_requests=completion.web_search_requests,
                cost_usd=completion.cost_usd,
            )
        )

    run_authored_write(conn, write)

    stored = read_coach_report(conn, new_id[0])
    assert stored is not None
    return _report_out(stored, prompt=p.prompt, stale=False)
