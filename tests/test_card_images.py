"""Scryfall pacing in card_images: its published limits, honoured on our side.

Scryfall allows 10 requests a second by id and 2 a second by name, and holds
back a client for 30 seconds after a 429, which "it is not acceptable to
ignore" (https://scryfall.com/docs/api/rate-limits). A dashboard page asks for
every picture at once, so the pacing is what keeps a first view of a long list
inside those limits. The numbers below are those limits, not values read from
a run.

Every test owns the clock and the sleep, and replaces card_images._fetch, the
one function that touches the network: nothing here waits in real time or
leaves the machine (docs/testing.md).
"""

import urllib.error
import urllib.parse

import pytest

from sensei_top import card_images

# The fake clock's float sums may land a hair under a limit (0.1 + 0.4).
EPS = 1e-9


class FakeTime:
    """A clock that only moves when the code under test sleeps, or when the
    test sets it. ``on_sleep``, when set, runs once during the next sleep:
    what another thread does while this one waits."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []
        self.advance_on_sleep = True
        self.on_sleep = None

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        if self.advance_on_sleep:
            self.now += seconds
        if self.on_sleep is not None:
            # Cleared before the call, so a sleep inside it cannot fire it again.
            callback, self.on_sleep = self.on_sleep, None
            callback()


class FakeScryfall:
    """Records when each URL left; answers by-id lookups for ids in
    ``unknown_ids`` with a 404, and the next ``refusals`` requests with a 429."""

    def __init__(self, time):
        self.time = time
        self.sent = []
        self.unknown_ids = set()
        self.refusals = 0

    def fetch(self, url):
        self.sent.append((url, self.time.now))
        if self.refusals:
            self.refusals -= 1
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
        if any(
            f"/cards/arena/{grp_id}?" in url or f"/cards/mtgo/{-grp_id}?" in url
            for grp_id in self.unknown_ids
        ):
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        return b"JPEG"

    def times(self, fragment):
        return [at for url, at in self.sent if fragment in url]


@pytest.fixture
def time(monkeypatch):
    fake = FakeTime()
    monkeypatch.setattr(card_images, "_clock", fake.clock)
    monkeypatch.setattr(card_images, "_sleep", fake.sleep)
    # A fresh schedule per test: the module's own is shared by the process.
    monkeypatch.setattr(card_images, "_pacing", card_images._Pacing())
    return fake


@pytest.fixture
def scryfall(time, monkeypatch):
    fake = FakeScryfall(time)
    monkeypatch.setattr(card_images, "_fetch", fake.fetch)
    return fake


# --- spacing ------------------------------------------------------------------


def test_two_lookups_by_id_leave_at_least_100_ms_apart_across_both_kinds(
    tmp_path, scryfall
):
    """One schedule for both kinds of picture: a whole card and a piece of art
    asked for at the same moment are still two requests to /cards/arena/."""
    assert card_images.get_image(tmp_path, 1) is not None
    assert card_images.get_art(tmp_path, 2) is not None

    first, second = scryfall.times("/cards/arena/")
    assert second - first >= 0.1 - EPS


def test_two_lookups_by_name_leave_at_least_500_ms_apart(tmp_path, scryfall):
    scryfall.unknown_ids = {1, 2}

    assert card_images.get_image(tmp_path, 1, name="Swamp") is not None
    assert card_images.get_art(tmp_path, 2, name="Island") is not None

    first, second = scryfall.times("/cards/named")
    assert second - first >= 0.5 - EPS


# --- refusals -----------------------------------------------------------------


def test_after_a_429_nothing_leaves_for_30_seconds_and_nothing_is_marked(
    tmp_path, time, scryfall
):
    scryfall.refusals = 1

    assert card_images.get_art(tmp_path, 1) is None
    assert len(scryfall.sent) == 1

    time.now = 29.9
    assert card_images.get_image(tmp_path, 2) is None
    assert card_images.get_art(tmp_path, 1) is None
    assert len(scryfall.sent) == 1, "a request left inside the 30-second pause"

    time.now = 30.0
    assert card_images.get_art(tmp_path, 1) is not None
    assert len(scryfall.sent) == 2

    assert list(tmp_path.rglob("*.missing")) == [], "a 429 is transient, never a miss"


def test_a_request_already_waiting_for_its_turn_does_not_leave_after_a_429(
    tmp_path, time, scryfall
):
    """A request can hold a turn and be asleep when another thread's request
    is refused: it must look again before it leaves, since Scryfall's 30
    seconds cover it too."""
    scryfall.unknown_ids = {1, 2}

    # A: a lookup by id that 404s, then one by name that leaves.
    assert card_images.get_image(tmp_path, 1, name="Swamp") is not None
    assert len(scryfall.times("/cards/named")) == 1

    # Past the by-id gap, still short of the next by-name turn.
    time.now = 0.2
    refused = []

    def another_thread_is_refused():
        scryfall.refusals = 1
        refused.append(card_images.get_image(tmp_path, 3))

    time.on_sleep = another_thread_is_refused

    # B: its lookup by id 404s, then it sleeps until its by-name turn.
    assert card_images.get_image(tmp_path, 2, name="Island") is None

    assert refused == [None]
    assert len(scryfall.times("/cards/named")) == 1, "B's lookup by name left after a 429"
    for cache in (tmp_path, tmp_path / "art"):
        assert not (cache / "2.jpg").exists()
        assert not (cache / "2.missing").exists()
        assert not (cache / "3.missing").exists()


# --- which picture ------------------------------------------------------------
# Scryfall's names for the two pictures: 'normal' is the whole card, 'art_crop'
# the art alone. A swap would cache one as the other for good.


def _versions(scryfall, fragment):
    return [
        urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["version"]
        for url, _ in scryfall.sent
        if fragment in url
    ]


def test_a_whole_card_image_asks_for_normal_by_id_and_by_name(tmp_path, scryfall):
    scryfall.unknown_ids = {2}

    assert card_images.get_image(tmp_path, 1) is not None
    assert card_images.get_image(tmp_path, 2, name="Swamp") is not None

    assert _versions(scryfall, "/cards/arena/") == [["normal"], ["normal"]]
    assert _versions(scryfall, "/cards/named") == [["normal"]]


def test_art_asks_for_art_crop_by_id_and_by_name(tmp_path, scryfall):
    scryfall.unknown_ids = {2}

    assert card_images.get_art(tmp_path, 1) is not None
    assert card_images.get_art(tmp_path, 2, name="Swamp") is not None

    assert _versions(scryfall, "/cards/arena/") == [["art_crop"], ["art_crop"]]
    assert _versions(scryfall, "/cards/named") == [["art_crop"]]


def test_a_negative_id_asks_scryfalls_mtgo_route_then_the_name(tmp_path, scryfall):
    scryfall.unknown_ids = {-12553}

    assert card_images.get_image(tmp_path, -43399) is not None
    assert card_images.get_art(tmp_path, -12553, name="Mother of Runes") is not None

    assert [u for u, _ in scryfall.sent if "/cards/arena/" in u] == []
    assert _versions(scryfall, "/cards/mtgo/43399") == [["normal"]]
    assert _versions(scryfall, "/cards/mtgo/12553") == [["art_crop"]]
    assert _versions(scryfall, "/cards/named") == [["art_crop"]]


# --- giving up ----------------------------------------------------------------


def test_a_request_whose_turn_is_more_than_2_seconds_away_gives_up(tmp_path, time, scryfall):
    """Six lookups by name asked for at one instant, as a page's thumbnails
    are: turns at 0, 0.5, 1, 1.5 and 2 seconds leave, the sixth's at 2.5 s
    gives up rather than hold a worker thread, and caches nothing. The
    sleep here does not move the clock, which is what six threads asking at
    once look like."""
    time.advance_on_sleep = False
    scryfall.unknown_ids = {1, 2, 3, 4, 5, 6}

    results = [card_images.get_image(tmp_path, grp_id, name="Swamp") for grp_id in range(1, 7)]

    assert all(path is not None for path in results[:5])
    assert results[5] is None
    assert len(scryfall.times("/cards/named")) == 5
    assert max(time.sleeps) <= 2.0 + EPS
    assert not (tmp_path / "6.missing").exists()
    assert not (tmp_path / "6.jpg").exists()
