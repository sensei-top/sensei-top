"""A thin, fail-soft wrapper over the system keyring (Windows Credential
Manager, Secret Service on Linux, Keychain on macOS).

Generic on purpose: it stores and returns strings under the service
``sensei-top`` and knows nothing about what they are for. Which credential
wins, and in what order, is decided by the callers (``llm/config.py`` for the
metered Claude key — AGENTS.md non-negotiable #5 — and ``metagame/config.py``
for the free TopDeck.gg one), never here.

Nothing here raises. A machine with no usable backend (``keyring``'s ``fail``
and ``null`` backends count as none) reads as "nothing stored" without a
warning; a backend that exists but errors logs a WARNING — never the value —
and reads as "nothing stored" too, so the caller falls back to the config
file. ``keyring`` is imported inside the functions: probing a backend can be
slow and must not cost unrelated commands at import time.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

SERVICE = "sensei-top"
CLAUDE = "claude"
TOPDECK = "topdeck"


def _backend():
    """The active keyring backend, or ``None`` when there is none usable."""
    try:
        import keyring
        from keyring.backends import fail, null

        backend = keyring.get_keyring()
    except Exception as exc:
        log.warning("could not load the system keyring: %s", exc)
        return None
    if isinstance(backend, (fail.Keyring, null.Keyring)):
        return None
    return backend


def backend_name() -> str | None:
    """A readable name for the backend in use, or ``None`` when there is no
    usable one."""
    backend = _backend()
    if backend is None:
        return None
    return str(getattr(backend, "name", None) or type(backend).__name__)


def get(username: str) -> str | None:
    """The stored value, or ``None`` when unset, empty, or unreadable."""
    backend = _backend()
    if backend is None:
        return None
    try:
        value = backend.get_password(SERVICE, username)
    except Exception as exc:
        log.warning("could not read %r from the system keyring: %s", username, exc)
        return None
    return value or None


def set(username: str, value: str) -> bool:
    """Store ``value``; ``False`` (and a WARNING, if a backend errored) when it
    could not be stored, so the caller can write the file instead."""
    backend = _backend()
    if backend is None:
        return False
    try:
        backend.set_password(SERVICE, username, value)
    except Exception as exc:
        log.warning("could not write %r to the system keyring: %s", username, exc)
        return False
    return True


def delete(username: str) -> bool:
    """Remove the stored value; ``True`` only when it is certainly gone
    (including when there was none), ``False`` when there is no backend or
    the backend errored. A delete error is never read as "nothing stored":
    some backends raise it for a cancelled prompt or any failure."""
    backend = _backend()
    if backend is None:
        return False
    try:
        if backend.get_password(SERVICE, username) is None:
            return True
        backend.delete_password(SERVICE, username)
    except Exception as exc:
        log.warning("could not delete %r from the system keyring: %s", username, exc)
        return False
    return True
