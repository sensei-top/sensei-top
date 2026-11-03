"""What ``ai/`` lends a core read: one optional field per seam, typed by a
Protocol declared beside the core read that takes it (docs/architecture.md,
"Who may know what").

Contract: a field is ``None`` unless ``sensei_top.ai.providers`` filled it,
always so with ``ai/`` absent, and the read degrades to its core half then.
The providers live on the app ``create_app`` built, never in a module
global: an app built with ``ai/`` hidden carries none, even in a process
where ``sensei_top.ai`` is already imported.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from sensei_top.api.routes.rcq import RcqPromptProvider
    from sensei_top.table.intermission import BreakBriefProvider


@dataclass(frozen=True, slots=True)
class Providers:
    """Every seam's provider, each ``None`` by default."""

    rcq_prompt: RcqPromptProvider | None = None
    break_briefs: BreakBriefProvider | None = None


NO_PROVIDERS = Providers()


def providers_of(app: FastAPI) -> Providers:
    """``app``'s providers; ``NO_PROVIDERS`` for an app ``create_app`` did
    not build."""
    return getattr(app.state, "providers", NO_PROVIDERS)
