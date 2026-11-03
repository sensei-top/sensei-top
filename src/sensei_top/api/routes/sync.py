"""The cloud backup's read side — ``/api/sync/payloads``. A ``GET`` on the
read-only connection: it writes nothing and calls nothing outside the
machine; the desktop shell's main process uploads what it returns.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from sensei_top.api.deps import Conn
from sensei_top.api.models.sync import SyncPayload
from sensei_top.sync import build_payloads

router = APIRouter()


@router.get("/api/sync/payloads", response_model=list[SyncPayload], tags=["sync"])
def sync_payloads(conn: Conn) -> list[dict[str, Any]]:
    """Every backed-up match with its digest, oldest first, all of them on
    every call: the caller pushes the ones whose digest differs from the one
    it last pushed, which catches a rebuild or a pick that a timestamp would
    miss."""
    return [asdict(payload) for payload in build_payloads(conn)]
