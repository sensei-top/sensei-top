"""Stage progress for a slow GET: the in-memory registry a build records its
stages in, and ``GET /api/progress/{key}``, which the page polls while that
GET is pending (``docs/guide.md``, "Stage progress").

Nothing here touches the database: the registry lives on
``app.state.progress`` and dies with the process. A stage is an id, never
prose; the page keys its own words.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, get_args
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from sensei_top.guide.bundle import Progress, no_progress

Stage = Literal["matches", "field", "together"]
STAGES: tuple[str, ...] = get_args(Stage)

# An entry outlives its last update by this long, so a poll that lands just
# after the build finished still reads the last stage instead of a 404.
TTL_SECONDS = 60.0


class ProgressOut(BaseModel):
    stage: Stage = Field(description="The stage the build is in now, an id the page keys.")
    done: int | None = Field(
        default=None,
        description="Items of this stage finished; null where the stage has no count.",
    )
    total: int | None = Field(
        default=None, description="Items this stage has in all; null where it has no count.",
    )


@dataclass(slots=True)
class _Entry:
    stage: str
    done: int | None
    total: int | None
    updated: float


class ProgressRegistry:
    """``key → (stage, done, total, updated)``, shared by the threadpool
    workers that run sync routes, hence the lock. Entries are dropped lazily,
    on the next ``record`` or ``read`` after ``ttl`` seconds without an
    update; nothing runs in the background."""

    def __init__(
        self, *, ttl: float = TTL_SECONDS, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}

    def _prune(self, now: float) -> None:
        stale = [key for key, entry in self._entries.items() if now - entry.updated > self._ttl]
        for key in stale:
            del self._entries[key]

    def record(
        self, key: str, stage: str, done: int | None = None, total: int | None = None,
    ) -> None:
        """Raises ``ValueError`` on a stage not in ``STAGES``: a typo at a
        call site would otherwise reach the page as a stage it has no words
        for."""
        if stage not in STAGES:
            raise ValueError(f"unknown progress stage {stage!r}")
        with self._lock:
            now = self._clock()
            self._prune(now)
            self._entries[key] = _Entry(stage, done, total, now)

    def read(self, key: str) -> ProgressOut | None:
        with self._lock:
            self._prune(self._clock())
            entry = self._entries.get(key)
            if entry is None:
                return None
            return ProgressOut(stage=entry.stage, done=entry.done, total=entry.total)

    def reporter(self, key: str | None) -> Progress:
        """The ``Progress`` a build is handed: records under ``key``, or does
        nothing when ``key`` is ``None`` (the request asked for no progress)."""
        if key is None:
            return no_progress

        def report(stage: str, done: int | None = None, total: int | None = None) -> None:
            self.record(key, stage, done, total)

        return report


def progress_key(raw: str | None) -> str | None:
    """A GET's ``?progress=`` value as the registry's key: the UUID in its
    canonical lowercase form, so the poll matches however the page spelled
    it. Anything that is not a UUID is ``None``, and the GET runs as if no
    progress were asked for."""
    if raw is None:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


def progress_reporter(request: Request, raw: str | None) -> Progress:
    """The ``Progress`` for a route to pass down, from its ``?progress=``."""
    return request.app.state.progress.reporter(progress_key(raw))


router = APIRouter()


# The parameter is `key`, not `uuid`: tests/test_i18n.py's GET sweep fills
# every path's parameters from a fixed set of names, and `key` is one.
@router.get("/api/progress/{key}", response_model=ProgressOut, tags=["progress"])
def progress(key: UUID, request: Request) -> ProgressOut:
    """The latest stage a build recorded under ``key``. 404 when nothing is
    recorded under it, or its entry expired; 422 when ``key`` is not a UUID."""
    found = request.app.state.progress.read(str(key))
    if found is None:
        raise HTTPException(status_code=404)
    return found
