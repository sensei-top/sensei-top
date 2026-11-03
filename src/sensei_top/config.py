"""Where the config file lives, and nothing about what is in it. Every
feature that keeps a table there resolves the path through this module; see
docs/llm.md, "Credential resolution".
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["config_path"]

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
