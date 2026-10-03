"""Where the TopDeck.gg credential comes from — the only question this module
answers.

Resolution order, first match wins:

1. ``TOPDECK_API_KEY`` in the environment.
2. ``[topdeck]`` in ``llm.config.config_path()`` — the same
   ``~/.config/sensei-top/config.toml`` the Claude credential lives in
   (``$XDG_CONFIG_HOME`` if set), written by ``sensei-top config
   --set-topdeck-key``.

Nothing here raises. A missing file, a missing table, or a malformed one all
resolve the same way ``llm/config.py`` and ``metagame/source.py`` do: log a
warning and hand back the "not configured" state (``None``), never an
exception.

This is a sibling to ``llm/config.py``, sharing only ``config_path()`` — not
an extension of it. TopDeck is not the metered, billing credential
AGENTS.md's non-negotiable #5 governs (the key exists for rate-limiting and
attribution, never billing); it is one of "the free downloads that remain",
so it is configured the same way but by its own module, and an unconfigured
TopDeck key means the metagame corpus refresh simply skips that source —
no different from any other unreachable download.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass

from sensei_top.llm.config import config_path

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TopDeckConfig:
    api_key: str


def load() -> TopDeckConfig | None:
    """``None`` means "not configured" — every caller must treat an
    unconfigured TopDeck source exactly like an unreachable one: skip it,
    keep whatever is cached, never raise."""
    env_key = os.environ.get("TOPDECK_API_KEY")
    if env_key:
        return TopDeckConfig(api_key=env_key)
    return _load_file()


def _load_file() -> TopDeckConfig | None:
    path = config_path()
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None

    topdeck = data.get("topdeck")
    if not isinstance(topdeck, dict):
        return None
    api_key = topdeck.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        log.warning("%s's [topdeck] table has no api_key", path)
        return None
    return TopDeckConfig(api_key=api_key)
