"""Where the TopDeck.gg credential comes from — the only question this module
answers.

Resolution order, first match wins:

1. ``TOPDECK_API_KEY`` in the environment.
2. The system keyring (``secrets.get(secrets.TOPDECK)``), where one exists.
3. ``[topdeck]`` in ``llm.config.config_path()`` — the same
   ``~/.config/sensei-top/config.toml`` the Claude credential lives in
   (``$XDG_CONFIG_HOME`` if set), which ``sensei-top config
   --set-topdeck-key`` writes only when the keyring does not take the key.

Nothing here raises. A missing file, a missing table, or a malformed one all
resolve the same way ``llm/config.py`` and ``metagame/source.py`` do: log a
warning and hand back the "not configured" state (``None``), never an
exception.

A sibling to ``llm/config.py``, sharing only ``config_path()``: TopDeck's key
is a free download source's, not the metered credential AGENTS.md's
non-negotiable #5 governs. See docs/metagame.md, "A second source:
TopDeck.gg".
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass

from sensei_top import secrets
from sensei_top.llm.config import config_path

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TopDeckConfig:
    api_key: str


def load() -> TopDeckConfig | None:
    """``None`` means "not configured" — every caller must treat an
    unconfigured TopDeck source exactly like an unreachable one: skip it,
    keep whatever is cached, never raise."""
    resolved = _resolve(warn=True)
    return None if resolved is None else TopDeckConfig(api_key=resolved[0])


def key_source() -> str | None:
    """Where the key ``load()`` would use comes from: ``"env"``,
    ``"keyring"`` or ``"file"``, or ``None`` when there is none. The same
    resolution as ``load()``, minus its warning about a ``[topdeck]`` table
    with no key."""
    resolved = _resolve(warn=False)
    return None if resolved is None else resolved[1]


def _resolve(*, warn: bool) -> tuple[str, str] | None:
    """``(key, source)``, first match wins."""
    env_key = os.environ.get("TOPDECK_API_KEY")
    if env_key:
        return env_key, "env"
    keyring_key = secrets.get(secrets.TOPDECK)
    if keyring_key:
        return keyring_key, "keyring"
    file_key = _load_file(warn=warn)
    return None if file_key is None else (file_key, "file")


def _load_file(*, warn: bool) -> str | None:
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
        if warn:
            log.warning("%s's [topdeck] table has no api_key", path)
        return None
    return api_key
