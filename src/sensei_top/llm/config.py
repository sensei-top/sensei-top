"""Where the Claude credential comes from — the only question this module
answers.

Resolution order, first match wins:

1. ``ANTHROPIC_API_KEY`` in the environment.
2. The system keyring (``secrets.get("claude")``), where one exists.
3. ``[claude]`` in ``config_path()`` (``~/.config/sensei-top/config.toml``;
   ``$XDG_CONFIG_HOME`` if set; ``%APPDATA%\\sensei-top\\config.toml`` on
   Windows, where an old ``~/.config`` file is still used until moved),
   written by ``sensei-top config --set-key``.

Nothing here raises. A missing file, a missing table, or a malformed one all
resolve the same way ``metagame/source.py`` treats an unreachable host: log a
warning and hand back the "not configured" state (``None``) rather than an
exception, because a feature this optional must never be what breaks a
request. Every caller checks for ``None`` and falls back to the prompt/import
path — see ``docs/llm.md``.

``load_coach()`` is the same resolution, with the ``[claude.coach]`` table's
``model``/``effort``/``web_search`` overriding the base ``[claude]`` values
for the coach report only. The other three narrative routes keep calling
``load()``, which this table never affects.
"""

from __future__ import annotations

import logging
import os
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from sensei_top import secrets

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"


@dataclass(frozen=True, slots=True)
class LLMConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    web_search: bool = True


_warned_old_config = False


def config_path() -> Path:
    """The one config file every reader and writer agrees on. Order: an
    explicit ``XDG_CONFIG_HOME`` on every platform (tests rely on it); on
    Windows ``%APPDATA%``, unless only the old ``~/.config`` file exists;
    otherwise ``~/.config``. Only where the file is found changes here, never
    how the credential inside it is resolved."""
    global _warned_old_config
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "sensei-top" / "config.toml"
    old = Path.home() / ".config" / "sensei-top" / "config.toml"
    appdata = os.environ.get("APPDATA")
    if sys.platform == "win32" and appdata:
        new = Path(appdata) / "sensei-top" / "config.toml"
        if not new.exists() and old.exists():
            if not _warned_old_config:
                _warned_old_config = True
                log.warning(
                    "config file read from %s; on Windows it now belongs at %s, so move it there",
                    old,
                    new,
                )
            return old
        return new
    return old


def load() -> LLMConfig | None:
    """``None`` means "not configured" — a state every caller must handle,
    not an error any of them should raise past. The key comes from the
    environment, then the keyring, then the file; model and effort always come
    from the file's ``[claude]`` table (they are not secrets)."""
    path = config_path()
    claude = _read_claude_table(path)
    resolved = _resolve_key(path, claude, warn=True)
    if resolved is None:
        return None
    api_key, _source = resolved
    model = (claude or {}).get("model")
    effort = (claude or {}).get("effort")
    return LLMConfig(
        api_key=api_key,
        model=model if isinstance(model, str) and model else DEFAULT_MODEL,
        effort=effort if isinstance(effort, str) and effort else DEFAULT_EFFORT,
    )


def key_source() -> str | None:
    """Where the key ``load()`` would use comes from: ``"env"``,
    ``"keyring"`` or ``"file"``, or ``None`` when there is none. The same
    resolution as ``load()``, minus its warning about a file with no key:
    ``config --json`` asks this every time the shell reads its settings."""
    path = config_path()
    resolved = _resolve_key(path, _read_claude_table(path), warn=False)
    return None if resolved is None else resolved[1]


def _resolve_key(path: Path, claude: dict | None, *, warn: bool) -> tuple[str, str] | None:
    """``(key, source)``, first match wins: the environment, the keyring,
    the file's ``[claude]`` table."""
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key, "env"
    keyring_key = secrets.get(secrets.CLAUDE)
    if keyring_key:
        return keyring_key, "keyring"
    if claude is not None:
        file_key = claude.get("api_key")
        if isinstance(file_key, str) and file_key:
            return file_key, "file"
        if warn:
            # Only now, with no key from anywhere: a file without [claude] is
            # the normal state once the key lives in the keyring.
            log.warning("%s has no [claude] table with an api_key", path)
    return None


def load_coach() -> LLMConfig | None:
    """``load()``'s result with the ``[claude.coach]`` overrides applied, or
    ``None`` when there is no credential at all (same "no credential, no
    call" rule as every other route — AGENTS.md non-negotiable #5)."""
    base = load()
    if base is None:
        return None
    overrides = _load_coach_overrides()
    if overrides is None:
        return base
    model, effort, web_search = overrides
    return replace(
        base,
        model=model if model is not None else base.model,
        effort=effort if effort is not None else base.effort,
        web_search=web_search if web_search is not None else base.web_search,
    )


def _read_claude_table(path: Path) -> dict | None:
    """The ``[claude]`` table (``{}`` when the file has none), or ``None``
    when the file is missing or unreadable (the latter warns) — never
    raises."""
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None
    claude = data.get("claude")
    if not isinstance(claude, dict):
        return {}
    return claude


def _load_coach_overrides() -> tuple[str | None, str | None, bool | None] | None:
    """``(model, effort, web_search)``, each ``None`` when absent or
    malformed — never raises, same warn-and-fall-back posture as
    ``_read_claude_table``. Returns ``None`` outright when there is no
    ``[claude.coach]`` table at all, so ``load_coach()`` can tell "no
    overrides" apart from "every override absent" (same result either way,
    but this keeps the malformed-table warning distinct from the common
    case of a user who has simply never set a coach override)."""
    path = config_path()
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        log.warning("could not read %s: %s", path, exc)
        return None

    claude = data.get("claude")
    if not isinstance(claude, dict):
        return None
    coach = claude.get("coach")
    if not isinstance(coach, dict):
        return None

    model = coach.get("model")
    if not (isinstance(model, str) and model):
        if "model" in coach:
            log.warning("%s's [claude.coach] model is not a valid string; ignoring", path)
        model = None

    effort = coach.get("effort")
    if not (isinstance(effort, str) and effort):
        if "effort" in coach:
            log.warning("%s's [claude.coach] effort is not a valid string; ignoring", path)
        effort = None

    web_search = coach.get("web_search")
    if not isinstance(web_search, bool):
        if "web_search" in coach:
            log.warning("%s's [claude.coach] web_search is not a valid boolean; ignoring", path)
        web_search = None

    return (model, effort, web_search)
