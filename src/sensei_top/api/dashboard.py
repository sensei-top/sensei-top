"""The built dashboard, served from ``web/dist``, with a page's address
answered by the page.

The dashboard is one page, and an address inside it (``/matches/abc``,
``/decks/x/guide``) names no file in ``web/dist``. Starlette's
``StaticFiles`` answers ``index.html`` at ``/`` and 404 everywhere else,
so a reload or a bookmark on any other address would fail.
``DashboardFiles`` answers ``index.html`` where the parent would answer
404 and leaves what to show for the address to the page.

Two kinds of path keep their 404:

1. ``api`` and everything under it. This mount is at ``/``, so an API
   path that no route takes arrives here. It stays a JSON 404: a page
   with status 200 in answer to a mistyped API path would tell its
   caller that the request succeeded.
2. Everything under ``assets``. Vite names each file there by its hash,
   so a missing one is a page from an older build asking for a file the
   new build replaced. HTML in answer to a request for a script fails
   later and less clearly than a 404 does.

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

_SEPARATORS = re.compile(r"[\\/]+")


def _reserved(path: str) -> bool:
    """Whether ``path``'s first non-empty segment, split on either
    separator, is ``api`` or ``assets``."""
    return _SEPARATORS.split(path.lstrip("\\/"), maxsplit=1)[0] in ("api", "assets")


class DashboardFiles(StaticFiles):
    """``StaticFiles`` for ``web/dist`` that answers ``index.html`` where the
    parent would answer 404, except under ``api`` and ``assets``."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """The parent's answer whenever it finds a file. Its 404, raised or
        returned, becomes ``index.html`` for a GET or a HEAD of a page's path.
        Any other status stands, and so does a 404 under ``api`` or
        ``assets``."""
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or _reserved(path):
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not _reserved(path):
            return await super().get_response("index.html", scope)
        return response
