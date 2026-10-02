"""Card pictures: grp_id -> a JPEG on disk, fetched lazily from Scryfall.

Two kinds of picture, each with its own cache and neither answering for
the other: the whole card (Scryfall's ``normal``, ``{grp_id}.jpg``) and
the card's art alone (Scryfall's ``art_crop``, ``art/{grp_id}.jpg``).

The third and last sanctioned outbound call (AGENTS.md rule 5), added
deliberately: the dashboard shows card thumbnails, the log carries no art, and
downloading Scryfall's full image archive up front would cost gigabytes for a
collection of which a player ever sees a sliver. So pictures are fetched one at
a time, the first time a card is actually shown, and cached on disk forever —
a printing's picture does not change.

Unlike the other two downloads, the request here names a card: the grp_id is
in the URL. That id comes from the user's own match history, so this is the
one call that reveals anything derived from game data (which cards have
appeared in your games — never when, against whom, or with what result). It
was an explicit user decision to accept that trade for lazy loading; anyone
uncomfortable with it can leave images off by staying offline — every failure
degrades to the card's name.

Arena-exclusive printings (full-art basics, alchemy rebalances, and similar)
have no Scryfall ``arena_id`` at all, so the by-id lookup 404s for them even
though Scryfall has the card under other printings. When the card's name is
already known (the local ``cards`` table, populated by ``sensei-top
cards``), a second request retries by exact name. That is a deliberate,
known-imprecise fallback: it returns *a* printing of the card, not
necessarily the one Arena rendered — accepted because a correct card with the
wrong art beats no art at all, and rejected as the *first* attempt because the
by-id lookup, when it succeeds, is exact.

Scryfall's own rules (https://scryfall.com/docs/api, read 2026-09-28) are
why the art is a second download and not a crop of the first: a card
image may not have its artist's name or its copyright line cropped,
covered or clipped off, and art shown alone must leave the artist and the
source identifiable in the same interface. docs/attribution.md carries
the wording.

Pacing. Scryfall publishes hard limits: 10 requests a second for a lookup
by id, 2 a second for a lookup by name, and 30 seconds of limited access
after a 429, which "it is not acceptable to ignore". A page asks for all
its pictures at once, so ``_get`` spaces the requests itself, one lock for
both kinds of picture: a lookup by id leaves no sooner than 100 ms after
the one before it, a lookup by name no sooner than 500 ms.

Fail-soft rules:
- offline / timeout / 5xx: return None, cache nothing, retry on the next view.
- a request whose turn is more than ``MAX_WAIT`` away: the same. The
  picture arrives on a later view; a queue of downloads never holds the
  API's worker threads.
- a 429: no request leaves for the next 30 seconds, and every call in
  that window returns None and caches nothing.
- Scryfall 404 on every attempt (by id, and by name if tried): write a
  ``.missing`` marker beside where the picture would be, so the miss is
  remembered and Scryfall is not asked again on every render.
- a half-written file must never be served: download to a unique temp file in
  the same directory, then ``os.replace`` — atomic on POSIX.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

# 'normal' is 488x680 — thumbnail-and-detail quality at ~100 KB.
# 'art_crop' is the illustration alone, a JPEG whose size varies with the
# card's frame. Scryfall asks that clients identify themselves; the redirect
# to the image file is followed by urllib automatically.
IMAGE_URL_BY_ARENA_ID = (
    "https://api.scryfall.com/cards/arena/{grp_id}?format=image&version={version}"
)
IMAGE_URL_BY_NAME = (
    "https://api.scryfall.com/cards/named?exact={name}&format=image&version={version}"
)
HEADERS = {"User-Agent": "sensei-top/0.1", "Accept": "*/*"}
TIMEOUT = 10.0

# Scryfall's published limits (https://scryfall.com/docs/api/rate-limits):
# 10 a second by id, 2 a second by name, 30 seconds held back after a 429.
MIN_GAP_BY_ID = 0.1
MIN_GAP_BY_NAME = 0.5
PAUSE_AFTER_429 = 30.0
# The longest a request may wait for its turn before giving up as transient.
MAX_WAIT = 2.0

# Module-level so a test can own time: nothing in the suite waits for real.
_clock = time.monotonic
_sleep = time.sleep


class _NotFoundError(Exception):
    """Scryfall answered this specific URL with a 404 — safe to negative-cache
    once every fallback has also been tried, unlike a transient failure."""


class _HeldBackError(Exception):
    """No request left: its turn was too far away, or a 429's pause is still
    running. Transient, like being offline — nothing is cached."""


class _Pacing:
    """When each lookup (by id, by name) may next leave, and until when a 429
    holds every request back. One instance, one lock, for both kinds of
    picture."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.next_turn: dict[str, float] = {}
        self.paused_until = float("-inf")


_pacing = _Pacing()


def image_path(cache_dir: Path, grp_id: int) -> Path:
    return cache_dir / f"{grp_id}.jpg"


def art_path(cache_dir: Path, grp_id: int) -> Path:
    return cache_dir / "art" / f"{grp_id}.jpg"


def _fetch(url: str) -> bytes:
    """The one function that touches the network."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def _take_turn(lookup: str, gap: float) -> float:
    """Reserve this request's turn and return how long to wait for it, or
    raise _HeldBackError without reserving anything."""
    with _pacing.lock:
        now = _clock()
        if now < _pacing.paused_until:
            raise _HeldBackError
        turn = max(now, _pacing.next_turn.get(lookup, now))
        if turn - now > MAX_WAIT:
            raise _HeldBackError
        _pacing.next_turn[lookup] = turn + gap
        return turn - now


def _get(url: str) -> bytes:
    """One paced request (see the module docstring's "Pacing")."""
    if urllib.parse.urlsplit(url).path.startswith("/cards/named"):
        wait = _take_turn("name", MIN_GAP_BY_NAME)
    else:
        wait = _take_turn("id", MIN_GAP_BY_ID)
    if wait > 0:
        _sleep(wait)
    with _pacing.lock:
        # A 429 may have arrived while this request waited for its turn.
        if _clock() < _pacing.paused_until:
            raise _HeldBackError
    try:
        return _fetch(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise _NotFoundError from exc
        if exc.code == 429:
            with _pacing.lock:
                _pacing.paused_until = max(
                    _pacing.paused_until, _clock() + PAUSE_AFTER_429
                )
            raise _HeldBackError from exc
        raise


def _download_version(grp_id: int, name: str | None, version: str) -> bytes:
    """Fetch one picture in Scryfall's ``version``: Arena's own id first, then
    the card's name as a fallback for printings Scryfall has no arena_id for."""
    try:
        return _get(IMAGE_URL_BY_ARENA_ID.format(grp_id=grp_id, version=version))
    except _NotFoundError:
        if name is None:
            raise
        return _get(
            IMAGE_URL_BY_NAME.format(name=urllib.parse.quote(name), version=version)
        )


def _download(grp_id: int, name: str | None) -> bytes:
    """Fetch one whole card image. Tests monkeypatch it directly."""
    return _download_version(grp_id, name, "normal")


def _download_art(grp_id: int, name: str | None) -> bytes:
    """Fetch one card's art alone, ``_download``'s twin. Tests monkeypatch it
    directly."""
    return _download_version(grp_id, name, "art_crop")


def _cached(
    path: Path, grp_id: int, name: str | None, download: Callable[[int, str | None], bytes]
) -> Path | None:
    """``path`` if it is on disk, else download it once; the fail-soft rules
    are the module docstring's. The miss marker sits beside ``path``."""
    if path.exists():
        return path
    miss = path.with_suffix(".missing")
    if miss.exists():
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        blob = download(grp_id, name)
    except _NotFoundError:
        # Scryfall has no picture under any URL we tried; remember, or every
        # render of a token would cost them a request.
        miss.touch()
        return None
    except (_HeldBackError, urllib.error.URLError, TimeoutError, OSError):
        return None  # transient (offline, say): no marker, try again next view
    if not blob:
        return None

    # Unique temp name: two concurrent requests for the same card must not
    # interleave writes; os.replace makes the last one win whole.
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(blob)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        return None
    return path


def get_image(cache_dir: Path, grp_id: int, name: str | None = None) -> Path | None:
    """The cached image's path, downloading on first miss. None means no image
    is available right now — the caller answers 404 and the UI shows the name.

    ``name`` enables the by-name fallback (see module docstring); pass None
    when the card table has not named this grp_id yet, and only the exact
    by-id lookup is tried.
    """
    return _cached(image_path(cache_dir, grp_id), grp_id, name, _download)


def get_art(cache_dir: Path, grp_id: int, name: str | None = None) -> Path | None:
    """The cached art's path, ``get_image``'s contract for the art alone: its
    own files under ``art/``, never the whole card's, and never a crop of it.
    """
    return _cached(art_path(cache_dir, grp_id), grp_id, name, _download_art)
