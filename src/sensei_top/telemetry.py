"""Error reports from the local API to Sentry, sent only with the user's yes.

Contracts:

- ``init`` starts the SDK only when ``SENSEI_TOP_SENTRY_DSN`` is non-empty and
  ``SENSEI_TOP_SENTRY_CONSENT`` is exactly ``1``. The desktop shell sets both,
  and ``SENSEI_TOP_SENTRY_USER`` (the account's ID) when signed in, at spawn,
  and restarts the server when any of them changes; nothing here reads the
  config file for them or re-reads them later.
- ``before_send`` runs every string in the event through
  ``scrub.scrub_text`` with the names ``diagnostics.known_names`` finds at
  that moment, then sets ``user`` to the account's ID alone (or drops it)
  and removes ``server_name``.

Traps:

1. ``release`` is always passed: left ``None``, the SDK runs ``git`` to guess
   one. ``server_name`` is always passed: left ``None``, the SDK sends the
   hostname, which often carries the user's name.
2. ``data_collection`` rather than ``send_default_pii``: from 2.73 the SDK
   deprecates the flag and warns when it is passed. Setting
   ``data_collection`` also switches off the SDK's own ``EventScrubber``,
   which is why every category it would have filtered is ``off`` here.
3. ``default_integrations=False`` drops the auto-enabling ones too; the
   default ones left out send things the policy does not list (``argv``
   carries ``--db`` and its path, ``modules`` every installed package,
   ``stdlib`` outbound-request breadcrumbs).
4. A ``before_send`` that raises makes the SDK drop the event, so a scrub
   failure never sends the unscrubbed text.
"""

from __future__ import annotations

import logging
import os
import platform
from collections.abc import Callable, Iterable, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from sensei_top import scrub

DSN_ENV = "SENSEI_TOP_SENTRY_DSN"
CONSENT_ENV = "SENSEI_TOP_SENTRY_CONSENT"
USER_ENV = "SENSEI_TOP_SENTRY_USER"

log = logging.getLogger(__name__)

DATA_COLLECTION: dict[str, Any] = {
    "user_info": False,
    "cookies": {"mode": "off"},
    "http_headers": {"request": {"mode": "off"}},
    "http_bodies": [],
    "url_query_params": {"mode": "off"},
    "graphql": {"document": False, "variables": False},
    "gen_ai": {"inputs": False, "outputs": False},
    "database_query_data": False,
    "queues": False,
    "stack_frame_variables": False,
    "frame_context_lines": 0,
}

# Expected answers, not faults: no database yet or a rebuild's lock (503),
# no Claude credential (503), Anthropic's own failure (502). A raised
# exception is reported whatever its status.
_FAILED_STATUS_CODES: set[int] = {500}

Event = dict[str, Any]


def _app_version() -> str:
    try:
        return version("sensei-top")
    except PackageNotFoundError:
        return "unknown"


def _scrubbed(value: Any, names: list[str]) -> Any:
    """``value`` with every string in it, at any depth, through
    ``scrub_text``. Keys are left alone; other values come back as they are."""
    if isinstance(value, str):
        return scrub.scrub_text(value, names)
    if isinstance(value, dict):
        return {key: _scrubbed(item, names) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrubbed(item, names) for item in value]
    return value


def make_before_send(
    user_id: str | None, names: Callable[[], Iterable[str]]
) -> Callable[[Event, dict[str, Any]], Event]:
    """The ``before_send`` hook: ``names`` is called once per event, so an
    opponent met since the server started is scrubbed too."""

    def before_send(event: Event, hint: dict[str, Any]) -> Event:
        known = list(names())
        cleaned: Event = _scrubbed(event, known)
        cleaned.pop("server_name", None)
        if user_id:
            cleaned["user"] = {"id": user_id}
        else:
            cleaned.pop("user", None)
        contexts = cleaned.setdefault("contexts", {})
        contexts["os"] = {"name": platform.system(), "version": platform.release()}
        return cleaned

    return before_send


def options(db_path: Path, environ: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """The keyword arguments for ``sentry_sdk.init``, or ``None`` when
    ``environ`` (default ``os.environ``) lacks the DSN or the consent. Holds
    no transport: the SDK's own sends to the DSN."""
    env = os.environ if environ is None else environ
    dsn = env.get(DSN_ENV, "").strip()
    if not dsn or env.get(CONSENT_ENV) != "1":
        return None
    user_id = env.get(USER_ENV, "").strip() or None

    def names() -> list[str]:
        from sensei_top.diagnostics import known_names

        return known_names(db_path)

    return {
        "dsn": dsn,
        "release": _app_version(),
        "server_name": "",
        "default_integrations": False,
        "integrations": [
            StarletteIntegration(failed_request_status_codes=_FAILED_STATUS_CODES),
            FastApiIntegration(failed_request_status_codes=_FAILED_STATUS_CODES),
            LoggingIntegration(level=None, event_level=logging.ERROR, sentry_logs_level=None),
            DedupeIntegration(),
            AtexitIntegration(),
        ],
        "data_collection": DATA_COLLECTION,
        "include_local_variables": False,
        "include_source_context": False,
        # The privacy policy lists what a report carries; earlier log lines
        # are not on it, hence no breadcrumbs (and ``level=None`` above).
        "max_breadcrumbs": 0,
        "auto_session_tracking": False,
        "traces_sample_rate": None,
        "send_client_reports": False,
        "before_send": make_before_send(user_id, names),
    }


def init(db_path: Path) -> bool:
    """Start error reports when the environment allows them (see the module
    docstring); True when the SDK started. A DSN the SDK rejects is a
    warning, never a failed ``serve``."""
    kwargs = options(db_path)
    if kwargs is None:
        return False
    try:
        sentry_sdk.init(**kwargs)
    except Exception as exc:  # the SDK raises its own BadDsn, among others
        log.warning("error reports not started: %s", type(exc).__name__)
        return False
    return True
