"""The formats an MTGO match is played in, and the codes MTGO writes for them.

The list itself lives in ``sensei_top/formats.py`` and is re-exported here
(seven formats, no "other"), so the projector and the API read the same
tuple instead of each keeping a copy. The projector cannot import ``api/``,
and ``api/`` should not import the projector, so neither owns it. The
``CHECK`` on ``mtgo_match_pick.format`` (migration 049) and the one on
``card_legality.format`` (migration 053) are the copies that cannot import
anything; ``tests/test_mtgo_decks_projector.py`` pins 049's, and the API's
``MtgoFormat``, to ``MTGO_FORMATS``.

``FORMAT_CODES`` maps a deck-store grouping's ``FormatCode`` attribute
(``projector/mtgo/decks.py``) to one of the seven. Six codes were seen in the
user's own store: ``CSTANDARD``, ``CPIONEER``, ``CMODERN``,
``CPAUPER``, ``CLEGACY`` and ``CPREMODERN``. ``CVINTAGE`` was not seen and
follows their pattern; if MTGO writes something else for Vintage, a Vintage
grouping is skipped like any other format outside the seven, never filed
under the wrong one. A code missing from this map (``CCMDR``, ``CFREEFORM``,
``CHULAHOOP``, an empty one) is not one of the seven.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from sensei_top.formats import FORMATS

MTGO_FORMATS: tuple[str, ...] = FORMATS

FORMAT_CODES: Mapping[str, str] = MappingProxyType({
    "CSTANDARD": "Standard",
    "CPIONEER": "Pioneer",
    "CMODERN": "Modern",
    "CPAUPER": "Pauper",
    "CLEGACY": "Legacy",
    "CVINTAGE": "Vintage",
    "CPREMODERN": "Premodern",
})
