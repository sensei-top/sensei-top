"""The leak finder's own cross-match output — ``/api/review/leaks``.
``LeakOut`` itself lives in ``models/common.py``: ``/api/guide/{key}``
surfaces the same leak rows at a different scope, so both routers share
one shape for it.

These drive the OpenAPI schema, which openapi-typescript turns into the
frontend's types — so field names here are the frontend's contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from sensei_top.api.models.common import LeakOut


class LeaksOut(BaseModel):
    leaks: list[LeakOut]
    narrative_available: bool = Field(
        True, description="kept for wire compatibility; GET .../narrative always serves a "
        "prompt, and POST there generates it with Claude when a credential is configured"
    )
