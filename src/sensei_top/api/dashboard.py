"""The built dashboard, served from ``web_dist``, with a page's address
answered by the page: ``index.html`` wherever the parent ``StaticFiles``
would answer 404, except under ``api`` (this mount is at ``/``, so an API
path no route takes arrives here and stays a JSON 404) and ``assets``.
Why each keeps its 404: docs/frontend.md, "Ports".

Traps:

1. ``path`` comes from ``StaticFiles.get_path``, which joins it with the
   system's own separator: ``assets\\app.js`` on Windows. The two
   exceptions compare the path's first part, split on either
   separator whatever the system, never a prefix spelled with ``/``.
   That is also what lets a test on Linux pin the rule.
2. The parent answers 404 two ways. It raises ``HTTPException(404)``,
   and in HTML mode, when the directory holds a ``404.html``, it returns
   that file with status 404 instead. Both are the same answer here.
3. It is a subclass and not a catch-all route on purpose. Files keep one
   code path, the parent's (its headers, its conditional requests, its
   refusal of a path that climbs out of the directory), and a mount is
   not in the OpenAPI schema, so ``web/src/types/api.ts`` does not
   change.
4. The fallback asks the parent for ``index.html`` by that name,
   whatever the request's path was. The request's path never reaches
   the file system a second time.

Verified against Starlette 1.6.0, whose ``get_response`` raises 405 for
a method other than GET or HEAD before it looks for any file.
"""

from __future__ import annotations

import re

from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# The dashboard's Content-Security-Policy. Starts from
# ``default-src 'self'``; each other directive is there for something in the
# built bundle (src/sensei_top/web_dist), found by reading it:
# - style-src 'unsafe-inline': React ``style={...}`` props under web/src
#   (and the chart library's) set style attributes, which only
#   'unsafe-inline' allows. No script is inline, so script-src stays 'self'.
# - font-src 'self' data:: the fonts are self-hosted under /assets, and
#   index-*.css also inlines two small woff2 files as ``url(data:font/woff2...)``.
# - img-src 'self': card images come from the API's own /api/cards/ routes
#   (components/CardImage.tsx, CardArt.tsx); the bundle holds no data: or
#   external image. The https:// strings in the bundle are links, not loads.
# - connect-src is not set: fetches go to the same origin, so default-src covers them.
# - frame-ancestors, base-uri, object-src: nothing needs otherwise.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; "
    "img-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

_SEPARATORS = re.compile(r"[\\/]+")


def _reserved(path: str) -> bool:
    """Whether ``path``'s first non-empty segment, split on either
    separator, is ``api`` or ``assets``."""
    return _SEPARATORS.split(path.lstrip("\\/"), maxsplit=1)[0] in ("api", "assets")


class DashboardFiles(StaticFiles):
    """``StaticFiles`` for ``web_dist`` that answers ``index.html`` where the
    parent would answer 404, except under ``api`` and ``assets``."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """The parent's answer whenever it finds a file. Its 404, raised or
        returned, becomes ``index.html`` for a GET or a HEAD of a page's path.
        Any other status stands, and so does a 404 under ``api`` or
        ``assets``."""
        response = await self._answer(path, scope)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        return response

    async def _answer(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or _reserved(path):
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not _reserved(path):
            return await super().get_response("index.html", scope)
        return response
