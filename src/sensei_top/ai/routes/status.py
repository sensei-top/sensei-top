"""``GET /api/llm/status``: whether a Claude credential is configured
(docs/llm.md, "The fallback").

Called through ``llm_config.load`` for the patch reason
``ai/routes/narrative.py``'s module docstring gives.
"""

from __future__ import annotations

from fastapi import APIRouter

from sensei_top.ai.llm import config as llm_config
from sensei_top.api.models.common import LLMStatus

router = APIRouter()


@router.get("/api/llm/status", response_model=LLMStatus, tags=["meta"])
def llm_status() -> LLMStatus:
    """Whether a Claude credential is resolved right now, and which
    model would be used — never the key itself
    (``sensei_top.ai.llm.config``). The dashboard reads this to
    decide whether a narrative surface offers a generate button or
    falls back to the copy-prompt path (``docs/llm.md``). No database
    connection needed: this is purely local config, not derived data.
    """
    cfg = llm_config.load()
    return LLMStatus(configured=cfg is not None, model=cfg.model if cfg else None)
