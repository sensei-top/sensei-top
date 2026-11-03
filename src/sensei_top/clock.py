"""The time now, as the ISO text every stored timestamp uses."""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = ["now_iso"]


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
