"""The loopback guard: one ASGI middleware, outermost on the app, that
answers three questions before any router runs — is this request addressed
to us (``Host``), did a page we serve make it (``Origin``, fetch metadata),
and — for anything that could write or spend — did *our own* dashboard make
it (a fixed header)? It also refuses to be framed. See ``api/app.py``'s
module docstring for why a loopback bind alone isn't enough.

Pure ASGI (``scope``/``receive``/``send``) and stdlib-only: nothing here
depends on Starlette or FastAPI, so the same class wraps any ASGI app
(``tests/test_guard.py`` wraps bare Starlette apps for the websocket and
lifespan branches). Importing it still runs ``sensei_top.api``'s
``__init__``, which re-exports ``create_app`` and so pulls FastAPI in —
which is why ``cli.py``'s ``_require_loopback`` imports ``is_loopback_host``
lazily.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from typing import Any
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

#: The dashboard sends this on every write (``web/src/api.ts``). Its
#: *presence*, not its value, is what a cross-site request can't forge
#: without a preflight — and nothing in this app ever sends
#: ``Access-Control-Allow-Origin``, so a preflighted request can never
#: succeed cross-origin in the first place.
CLIENT_HEADER = "X-Tracker-Client"

# Matches a bracketed IPv6 literal (``v6``, brackets excluded from the
# capture) or a bare name/IPv4 literal (``name``), each with an optional
# ``:port``. Starlette's own TrustedHostMiddleware splits a Host header on
# the first ``:`` and mangles ``[::1]:8000``; this pattern brackets that
# case out explicitly instead of reusing it.
_HOST_RE = re.compile(r"^(?:\[(?P<v6>[0-9a-f:.]+)\]|(?P<name>[a-z0-9.-]+))(?::\d{1,5})?$")


def is_loopback_host(host: str) -> bool:
    """True for exactly the literal ``"localhost"`` or an IP literal (no
    brackets) that is loopback (``127.0.0.0/8``, ``::1``). Never resolves a
    name — a hostname that merely *resolves* to loopback today, and might
    not tomorrow, is refused rather than trusted.

    Does no case-folding of its own; callers lowercase first. That keeps
    ``cli.py``'s ``_require_loopback`` behaving exactly as it did before it
    delegated its loopback check here.
    """
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _host_is_loopback(value: str) -> bool:
    """Parse a raw ``Host`` header value and answer whether it names
    loopback.

    Matched with ``fullmatch``, not ``match``: Python's ``$`` also matches
    just before a trailing newline, so ``"127.0.0.1\\n"`` would sail through
    ``_HOST_RE.match`` even with the literal ``^``/``$`` anchors in the
    pattern above. ``fullmatch`` anchors both ends for real.
    """
    match = _HOST_RE.fullmatch(value.strip().lower())
    if match is None:
        return False
    return is_loopback_host(match.group("v6") or match.group("name"))


def _origin_is_loopback(origin: str) -> bool:
    """``urlsplit`` raises ``ValueError`` on a malformed IPv6 netloc
    (``http://[::1``), and reading ``.port`` raises on an out-of-range port —
    so the whole parse sits in one ``try`` rather than trusting each piece to
    fail quietly. ``.hostname`` already strips IPv6 brackets and lowercases,
    so no separate folding is needed before ``is_loopback_host``. An opaque
    origin (the literal string ``"null"``) has no recognized scheme and
    falls out the same way as anything else that fails to parse: foreign.
    """
    try:
        parts = urlsplit(origin)
        if parts.scheme not in ("http", "https"):
            return False
        if parts.username is not None or parts.password is not None:
            return False
        hostname = parts.hostname
        if hostname is None:
            return False
        parts.port  # noqa: B018 - accessed for its ValueError, not its value
    except ValueError:
        return False
    return is_loopback_host(hostname)


def _first_headers(scope: dict[str, Any]) -> dict[str, str]:
    """ASGI header names arrive as lowercase bytes already; values are
    decoded as latin-1, the one encoding that cannot raise on arbitrary
    header bytes (HTTP header values are not guaranteed UTF-8). Only the
    first occurrence of a repeated header is kept — every check below reads
    a header at most once, so that is the only occurrence that matters.
    """
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers", ()):
        name = raw_name.decode("latin-1").lower()
        if name not in headers:
            headers[name] = raw_value.decode("latin-1")
    return headers


def _evaluate(
    method: str | None, headers: dict[str, str]
) -> tuple[int, str, str, str | None] | None:
    """Return ``(status, detail, header_name, value)`` for the first check
    this request fails, or ``None`` if it passes every one. The order is
    load-bearing: a DNS-rebinding page fails on ``Host`` before anything
    else runs, and a same-site page fails on ``Origin``/fetch metadata
    before ever reaching the header check.

    ``method`` is the HTTP method for an ``http`` scope, or ``None`` for a
    ``websocket`` scope, which has no method — so it can never qualify for
    the navigation exception in check 3, and never reaches check 4, which
    is HTTP-only.
    """
    host = headers.get("host")
    if host is None or not _host_is_loopback(host):
        return 400, "Host not allowed", "host", host

    origin = headers.get("origin")
    if origin is not None and not _origin_is_loopback(origin):
        return 403, "Cross-origin request refused", "origin", origin

    site = headers.get("sec-fetch-site")
    if site is not None and site.lower() in ("cross-site", "same-site"):
        mode = (headers.get("sec-fetch-mode") or "").lower()
        dest = (headers.get("sec-fetch-dest") or "").lower()
        navigating = method in ("GET", "HEAD") and mode == "navigate" and dest == "document"
        if not navigating:
            return 403, "Cross-origin request refused", "sec-fetch-site", site

    non_get = method is not None and method not in ("GET", "HEAD")
    if non_get and CLIENT_HEADER.lower() not in headers:
        return 403, f"Missing {CLIENT_HEADER} header", CLIENT_HEADER.lower(), None

    return None


def _framed(headers: list[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    """Append the two frame-denial headers to a *copy* of ``headers``, never
    mutating the list handed in. Applied to every response this app sends,
    including the guard's own rejections, so nothing on loopback can ever be
    framed by another origin.
    """
    return [
        *headers,
        (b"x-frame-options", b"DENY"),
        (b"content-security-policy", b"frame-ancestors 'none'"),
    ]


async def _reject(send: Any, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode("utf-8")
    headers = _framed(
        [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("latin-1")),
        ]
    )
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


class LoopbackGuard:
    """Outermost middleware on the app (``api/app.py::create_app``).

    Pure ASGI rather than ``BaseHTTPMiddleware`` for two reasons: it can
    refuse a websocket handshake before ``accept`` runs, and it never has to
    buffer a response body just to add a header to it.

    Any scope type other than ``http``/``websocket`` (namely ``lifespan``)
    passes straight through untouched — this guard has nothing to say about
    process startup/shutdown.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        is_ws = scope["type"] == "websocket"
        headers = _first_headers(scope)
        method = None if is_ws else scope.get("method", "")
        log_method = "WEBSOCKET" if is_ws else method
        path = scope.get("path", "")

        refusal = _evaluate(method, headers)
        if refusal is not None:
            status, detail, header_name, value = refusal
            log.warning(
                "refused %s %r: %s (%s=%r)", log_method, path, detail, header_name, value
            )
            if is_ws:
                await send({"type": "websocket.close", "code": 1008})
            else:
                await _reject(send, status, detail)
            return

        if is_ws:
            await self.app(scope, receive, send)
            return

        async def guarded_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                message = {**message, "headers": _framed(list(message.get("headers", [])))}
            await send(message)

        await self.app(scope, receive, guarded_send)
