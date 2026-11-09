"""The static site in `site/` keeps the promises its own copy makes.

Fifteen hand-written pages, no build step (`docs/frontend-site.md`, "The site"). The
checks read the HTML with the standard library's parser: the pages are small
enough that a structural slip (a second script, a refresh, a link to the wrong
repository, a drifted Fan Content notice) is the realistic failure, and none of
it shows in a browser until a visitor meets it.
"""

import json
import re
import shutil
import struct
import subprocess
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from test_attribution import WIZARDS_NOTICE

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
ORIGIN = "https://senseitop.com"
PROJECT = "https://github.com/sensei-top/sensei-top"
BEACON_SRC = "https://static.cloudflareinsights.com/beacon.min.js"
HERO_SCRIPT = "/hero.js"
# Answered by the Worker script in `worker/`, not by a file under `site/`.
DOWNLOADS = ("/download/windows", "/download/linux")
TARBALL = "/download/linux-tar"
STORE = "https://apps.microsoft.com/detail/9NZ5GQMCG1ZN"

# url path -> (file, html lang, the path of the same page in the other language)
PAGES = {
    "/": ("index.html", "en", "/pt-br/"),
    "/privacy/": ("privacy/index.html", "en", "/pt-br/privacy/"),
    "/pt-br/": ("pt-br/index.html", "pt-BR", "/"),
    "/pt-br/privacy/": ("pt-br/privacy/index.html", "pt-BR", "/privacy/"),
    "/terms/": ("terms/index.html", "en", "/pt-br/terms/"),
    "/pt-br/terms/": ("pt-br/terms/index.html", "pt-BR", "/terms/"),
    "/help/": ("help/index.html", "en", "/pt-br/help/"),
    "/pt-br/help/": ("pt-br/help/index.html", "pt-BR", "/help/"),
    # One page per search the app can win: the alternative to
    # Untapped, Arena on Linux and the Steam Deck, and Magic Online.
    "/untapped/": ("untapped/index.html", "en", "/pt-br/untapped/"),
    "/pt-br/untapped/": ("pt-br/untapped/index.html", "pt-BR", "/untapped/"),
    "/linux/": ("linux/index.html", "en", "/pt-br/linux/"),
    "/pt-br/linux/": ("pt-br/linux/index.html", "pt-BR", "/linux/"),
    "/mtgo/": ("mtgo/index.html", "en", "/pt-br/mtgo/"),
    "/pt-br/mtgo/": ("pt-br/mtgo/index.html", "pt-BR", "/mtgo/"),
}
ALL_PAGES = list(PAGES)
# The privacy policy and the terms of use, in both languages.
POLICY_PAGES = ["/privacy/", "/pt-br/privacy/", "/terms/", "/pt-br/terms/"]
# The landing's feature rows, one per place in the dashboard's rail.
FEATURE_IDS = {"home", "live", "matches", "decks", "field", "coach"}
# The 404 page is one page in both languages: no counterpart, no hreflang pair,
# no description meta. It is in every list the shell pages share and out of
# the ones about language and the head.
NOT_FOUND = "/404.html"
SHELL_PAGES = [*ALL_PAGES, NOT_FOUND]
FIRST_PAINT_LIMIT = 600 * 1024
WHOLE_PAGE_LIMIT = 1024 * 1024
LANDINGS = ["/", "/pt-br/"]
# Demo video language -> its catalogue folder and its poster.
DEMO_VIDEOS = {
    "en": ("en", "demo-poster.webp"),
    "pt-br": ("pt-BR", "demo-poster-pt-br.webp"),
}
DEMO_VIDEO_CAP = 5 * 1024 * 1024
# The poster is on the landing's first paint: the first frame, not a second video's worth.
DEMO_POSTER_LIMIT = 150 * 1024
DEMO_FADE = 0.3
# Each chapter's shot -> the catalogue key the dashboard names its place by
# (site_cut.py's CHAPTER_KEYS, restated so a swapped label shows).
DEMO_CHAPTER_KEYS = {
    "home": ("shell", "places", "home"),
    "live": ("shell", "places", "live"),
    "report": ("shell", "places", "matches"),
    "matchups": ("decks", "layout", "tabs", "matchups"),
    "field": ("shell", "places", "field"),
}
# The pages whose head carries the Open Graph card: every page but the 404.
OPEN_GRAPH_PAGES = ALL_PAGES


class Page(HTMLParser):
    """Collects what the checks need: tags with attributes, text, comments."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.comments: list[str] = []
        self.ids: set[str] = set()
        self._text: list[str] = []
        self._paragraph: list[str] | None = None
        self.paragraphs: list[str] = []
        self._skip = 0
        self.script_bodies: list[str] = []
        self._in_script = False
        self.links: list[tuple[str, str]] = []  # (href, text) of every <a>
        self._link: tuple[str, list[str]] | None = None
        self.labels: list[str] = []  # text of every <b>
        self._label: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == "a" and attributes.get("href"):
            self._link = (attributes["href"], [])
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag == "p":
            self._paragraph = []
        if tag == "b":
            self._label = []
        if tag == "script":
            self._in_script = True
        if tag in ("script", "style", "title"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            self.links.append((self._link[0], "".join(self._link[1])))
            self._link = None
        if tag == "p" and self._paragraph is not None:
            self.paragraphs.append("".join(self._paragraph))
            self._paragraph = None
        if tag == "b" and self._label is not None:
            self.labels.append("".join(self._label))
            self._label = None
        if tag == "script":
            self._in_script = False
        if tag in ("script", "style", "title"):
            self._skip -= 1

    def handle_data(self, data):
        if self._link is not None:
            self._link[1].append(data)
        if self._label is not None:
            self._label.append(data)
        if self._in_script:
            self.script_bodies.append(data)
        if self._skip:
            return
        self._text.append(data)
        if self._paragraph is not None:
            self._paragraph.append(data)

    def handle_comment(self, data):
        self.comments.append(data)

    @property
    def visible_text(self) -> str:
        return "".join(self._text)

    def find(self, name: str) -> list[dict[str, str | None]]:
        return [a for t, a in self.tags if t == name]


def load(url_path: str) -> tuple[str, Page]:
    name = "404.html" if url_path == NOT_FOUND else PAGES[url_path][0]
    raw = (SITE / name).read_text(encoding="utf-8")
    page = Page()
    page.feed(raw)
    return raw, page


def hrefs(page: Page) -> list[str]:
    return [a["href"] for a in page.find("a") if a.get("href")]


@pytest.mark.parametrize("url_path", ALL_PAGES)
def test_language_and_hreflang_pair(url_path):
    _, page = load(url_path)
    _, lang, other = PAGES[url_path]
    html_tag = page.find("html")[0]
    assert html_tag.get("lang") == lang

    alternates = {
        a["hreflang"]: a["href"]
        for a in page.find("link")
        if a.get("rel") == "alternate" and a.get("hreflang")
    }
    english = url_path if lang == "en" else other
    portuguese = url_path if lang == "pt-BR" else other
    assert alternates["en"] == ORIGIN + english
    assert alternates["pt-BR"] == ORIGIN + portuguese
    canonical = [a["href"] for a in page.find("link") if a.get("rel") == "canonical"]
    assert canonical == [ORIGIN + url_path]


@pytest.mark.parametrize("url_path", ALL_PAGES)
def test_language_link_goes_to_the_same_page_in_the_other_language(url_path):
    _, page = load(url_path)
    other = PAGES[url_path][2]
    other_lang = "pt-BR" if PAGES[url_path][1] == "en" else "en"
    links = [
        a for a in page.find("a") if a.get("hreflang") == other_lang and a.get("lang") == other_lang
    ]
    # One in the header, one in the footer.
    assert [a["href"] for a in links] == [other, other]


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_the_language_switcher_sits_outside_the_page_links(url_path):
    """A globe with EN and PT in the header, not a link among the page's sections."""
    raw, page = load(url_path)
    english = url_path == NOT_FOUND or PAGES[url_path][1] == "en"
    assert "hreflang" not in re.search(r"<nav>(.*?)</nav>", raw, re.S).group(1)
    groups = [a for a in page.find("div") if a.get("class") == "lang"]
    assert len(groups) == 1
    assert groups[0]["role"] == "group"
    assert groups[0]["aria-label"] == ("Language" if english else "Idioma")
    switcher = Page()
    switcher.feed(re.search(r'<div class="lang"[^>]*>(.*?)</div>', raw, re.S).group(1))
    assert [a.get("aria-current") for a in switcher.find("span")] == ["page"]
    assert switcher.visible_text == "ENPT"
    assert [text for _, text in switcher.links] == (["PT"] if english else ["EN"])
    assert "url(img/globe.svg)" in (SITE / "site.css").read_text(encoding="utf-8")
    assert (SITE / "img" / "globe.svg").is_file()


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_the_fan_content_notice_is_the_policy_wording(url_path):
    _, page = load(url_path)
    assert WIZARDS_NOTICE in page.paragraphs


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_no_page_says_the_word_ai(url_path):
    """Except the policy pages: Anthropic's terms require the rules coach to
    say an AI writes its answers, and those pages describe that coach."""
    raw, _ = load(url_path)
    if url_path in POLICY_PAGES:
        return
    assert not re.search(r"\bAI\b", raw)


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_every_github_link_is_the_project_its_sponsors_or_a_credited_repository(url_path):
    _, page = load(url_path)
    allowed = (
        PROJECT,
        "https://github.com/sponsors/sensei-top",
        "https://github.com/fbettega/MTG_decklistcache",
        "https://github.com/Badaro/MTGOFormatData",
    )
    github = [h for h in hrefs(page) if h.startswith("https://github.com")]
    assert any(h == PROJECT or h.startswith(PROJECT + "/") for h in github)
    for href in github:
        assert any(href == base or href.startswith(base + "/") for base in allowed), href


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_the_beacon_is_the_only_script_and_nothing_is_inline(url_path):
    raw, page = load(url_path)
    scripts = page.find("script")
    # The landings alone carry the hero's video script, same origin and deferred.
    expected = [BEACON_SRC, HERO_SCRIPT] if url_path in LANDINGS else [BEACON_SRC]
    assert [s["src"] for s in scripts] == expected
    assert all("defer" in s for s in scripts)
    script = scripts[0]
    beacon = json.loads(script["data-cf-beacon"])
    assert isinstance(beacon.get("token"), str) and beacon["token"]
    assert "".join(page.script_bodies).strip() == ""
    # No handler attribute is script either, and no stylesheet but our own.
    for _, attributes in page.tags:
        assert not [k for k in attributes if k.startswith("on")]
        # The CSP's style-src is 'self', which blocks a style attribute.
        assert "style" not in attributes
    sheets = [a["href"] for a in page.find("link") if a.get("rel") == "stylesheet"]
    assert sheets == ["/site.css"]
    assert not page.find("style")
    assert "javascript:" not in raw


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_no_page_refreshes_itself(url_path):
    _, page = load(url_path)
    for a in page.find("meta"):
        assert (a.get("http-equiv") or "").lower() != "refresh"


@pytest.mark.parametrize("url_path", ALL_PAGES)
def test_the_head_describes_the_page(url_path):
    raw, page = load(url_path)
    viewport = [a for a in page.find("meta") if a.get("name") == "viewport"]
    description = [a for a in page.find("meta") if a.get("name") == "description"]
    assert len(viewport) == 1
    assert len(description) == 1 and description[0]["content"]
    assert len(re.findall(r"<title>[^<]+</title>", raw)) == 1
    # The Open Graph card says what the page itself says.
    assert meta(page, "og:title") == [re.search(r"<title>([^<]+)</title>", raw).group(1)]
    assert [a["href"] for a in page.find("link") if a.get("rel") == "icon"] == ["/favicon.svg"]


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_images_carry_alt_text_and_the_mark_is_decorative(url_path):
    _, page = load(url_path)
    for img in page.find("img"):
        if img["src"] == "/img/mark.svg":
            assert img.get("alt") == ""
        else:
            assert img.get("alt"), img["src"]


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_local_references_resolve(url_path):
    _, page = load(url_path)
    own = "/404.html" if url_path == NOT_FOUND else url_path
    references = [h for h in hrefs(page) if h.startswith("/") and h not in (*DOWNLOADS, TARBALL)]
    references += [own + h for h in hrefs(page) if h.startswith("#")]
    references += [a["src"] for a in page.find("img")]
    references += [a["src"] for t in ("source", "track") for a in page.find(t)]
    references += [a["poster"] for a in page.find("video")]
    references += [a["src"] for a in page.find("script") if a["src"].startswith("/")]
    references += [
        urlsplit(a["content"]).path for a in page.find("meta") if a.get("property") == "og:image"
    ]
    references += [a["href"] for a in page.find("link") if a["href"].startswith("/")]
    assert references
    anchors: dict[str, Page] = {}
    for reference in references:
        path, _, fragment = reference.partition("#")
        target = SITE / path.lstrip("/")
        if path.endswith("/"):
            target = target / "index.html"
        assert target.is_file(), reference
        if fragment:
            if target not in anchors:
                anchors[target] = Page()
                anchors[target].feed(target.read_text(encoding="utf-8"))
            assert fragment in anchors[target].ids, reference


@pytest.mark.parametrize("url_path", ALL_PAGES)
def test_both_languages_share_the_anchors(url_path):
    """A link to a section works the same after the language switcher is pressed."""
    _, page = load(url_path)
    _, counterpart = load(PAGES[url_path][2])
    assert page.ids == counterpart.ids


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_landing_has_the_feature_rows_in_the_rails_order(url_path):
    _, page = load(url_path)
    rows = [a["id"] for t, a in page.tags if t == "section" and "feature" in (a.get("class") or "")]
    assert rows == ["home", "live", "matches", "decks", "field", "coach"]
    assert page.ids >= FEATURE_IDS


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_hero_image_is_the_only_eager_one_on_the_landing(url_path):
    """The eager picture is the video's poster, which comes before every image."""
    _, page = load(url_path)
    poster = landing_poster(url_path)
    content = [
        (t, a) for t, a in page.tags if t == "video" or (t == "img" and a["src"] != "/img/mark.svg")
    ]
    assert content[0][0] == "video"
    assert [a["poster"] for t, a in content if t == "video"] == [poster]
    preloaded = [a for a in page.find("link") if a.get("rel") == "preload" and a["as"] == "image"]
    assert [(a["href"], a.get("fetchpriority")) for a in preloaded] == [(poster, "high")]
    for img in [a for t, a in content if t == "img"]:
        assert img.get("loading") == "lazy", img["src"]
        assert "fetchpriority" not in img
        if img["src"].endswith(".svg"):
            drawn = re.search(
                r'<svg[^>]* width="(\d+)" height="(\d+)"',
                (SITE / img["src"].lstrip("/")).read_text(encoding="utf-8"),
            )
            assert (img["width"], img["height"]) == drawn.groups(), img["src"]
        else:
            matchups = "786" if url_path.startswith("/pt-br") else "759"
            focal = {"home": "1185", "match-report": "960", "matchups": matchups, "coach": "945"}
            name = img["src"].rsplit("/", 1)[1].removesuffix(".webp")
            expected = ("1326", focal[name]) if name in focal else ("1440", "900")
            assert (img["width"], img["height"]) == expected, img["src"]


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_hero_video_works_with_no_script_and_loads_nothing_until_started(url_path):
    """Without JS it is a poster with native controls; `hero.js` takes those away."""
    _, page = load(url_path)
    language = landing_language(url_path)
    video = page.find("video")[0]
    assert "controls" in video
    assert video["preload"] == "none"
    assert "muted" in video and "loop" in video and "playsinline" in video
    assert "autoplay" not in video
    assert video["aria-label"]
    assert [(a["src"], a["type"]) for a in page.find("source")] == [
        (f"/video/demo-{language}.mp4", "video/mp4")
    ]
    tracks = page.find("track")
    assert [(a["src"], a["kind"]) for a in tracks] == [(f"/video/demo-{language}.vtt", "captions")]
    assert tracks[0]["srclang"] == PAGES[url_path][1]
    controls = [a for a in page.find("div") if a.get("class") == "ctl"]
    assert len(controls) == 1 and "hidden" in controls[0]


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_chapter_strip_is_the_videos_chapters_and_links_to_the_feature_rows(url_path):
    raw, _ = load(url_path)
    chapters = demo_chapter_list(landing_language(url_path))["chapters"]
    strip = Page()
    strip.feed(re.search(r'<ol class="chapters".*?</ol>', raw, re.S).group(0))
    assert strip.find("ol")[0]["aria-label"]
    assert [text for _, text in strip.links] == [c["label"] for c in chapters]
    assert [float(a["data-start"]) for a in strip.find("a")] == [c["start"] for c in chapters]
    assert hrefs(strip) == ["#home", "#live", "#matches", "#decks", "#field"]


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_roadmap_section_comes_right_after_what_is_not_planned(url_path):
    _, page = load(url_path)
    sections = [a.get("id") for t, a in page.tags if t == "section" and a.get("class") == "card"]
    assert sections[sections.index("not-planned") + 1] == "roadmap"


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_roadmap_image_shows_from_700_px_beside_its_words(url_path):
    _, page = load(url_path)
    english = url_path == "/"
    src = "/img/roadmap-en.svg" if english else "/img/roadmap-pt-br.svg"
    alt = (
        "The same lists, drawn as a diagram."
        if english
        else "As mesmas listas, desenhadas como um diagrama."
    )
    images = [a for a in page.find("img") if a["src"] == src]
    assert [(a["alt"], a["loading"]) for a in images] == [(alt, "lazy")]
    assert "@media (max-width: 699px) { .roadmap-image { display: none; } }" in (
        SITE / "site.css"
    ).read_text(encoding="utf-8")
    assert ("An overlay for Arena." if english else "Um overlay para o Arena.") in page.visible_text


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_overlay_is_no_longer_listed_as_not_planned(url_path):
    raw, _ = load(url_path)
    block = re.search(r'<section class="card" id="not-planned">.*?</section>', raw, re.S).group(0)
    assert "overlay" not in block.lower()


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_landing_loads_the_hero_script_and_it_gates_autoplay(url_path):
    raw, _ = load(url_path)
    assert f'<script defer src="{HERO_SCRIPT}"></script>' in raw
    script = (SITE / "hero.js").read_text(encoding="utf-8")
    assert "matchMedia('(prefers-reduced-motion: no-preference)').matches" in script
    assert "matchMedia('(min-width: 700px)').matches" in script
    guard = re.search(r"^if \((.*)\) start\(\)$", script, re.M)
    assert guard, "autoplay must be one guarded start() at the end"
    conditions = {c.strip() for c in guard.group(1).split("&&")}
    assert conditions == {"motionAllowed", "wideEnough", "!navigator.connection?.saveData"}
    assert not re.search(r"^start\(\)", script, re.M)


@pytest.mark.parametrize("name", ["roadmap-en.svg", "roadmap-pt-br.svg"])
def test_the_roadmap_drawing_loads_nothing_and_runs_nothing(name):
    svg = (SITE / "img" / name).read_text(encoding="utf-8")
    assert "<script" not in svg and "<text" not in svg
    assert not re.search(r'href="(?!#)', svg)


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_landing_preloads_the_latin_font_the_stylesheet_uses(url_path):
    _, page = load(url_path)
    css = (SITE / "site.css").read_text(encoding="utf-8")
    preloads = [a for a in page.find("link") if a.get("rel") == "preload" and a["as"] != "image"]
    assert [a["href"] for a in preloads] == ["/fonts/inter-latin-wght-normal.woff2"]
    for link in preloads:
        assert link["as"] == "font" and link["type"] == "font/woff2"
        assert "crossorigin" in link
        assert link["href"].removeprefix("/") in css


def landing_language(url_path: str) -> str:
    return "en" if url_path == "/" else "pt-br"


def landing_poster(url_path: str) -> str:
    return "/img/" + DEMO_VIDEOS[landing_language(url_path)][1]


def meta(page: Page, key: str, name: str = "property") -> list[str]:
    return [a["content"] for a in page.find("meta") if a.get(name) == key]


def plane() -> str:
    """`--plane` on `:root` in the stylesheet: the colour `theme-color` must be."""
    match = re.search(r"--plane:\s*(#[0-9a-fA-F]{6})\s*;", (SITE / "site.css").read_text("utf-8"))
    assert match
    return match.group(1).lower()


@pytest.mark.parametrize("url_path", OPEN_GRAPH_PAGES)
def test_the_head_carries_the_open_graph_card(url_path):
    _, page = load(url_path)
    _, lang, _ = PAGES[url_path]
    english = lang == "en"
    assert meta(page, "og:type") == ["website"]
    assert meta(page, "og:site_name") == ["Sensei Top"]
    assert meta(page, "og:url") == [ORIGIN + url_path]
    assert meta(page, "og:description") == meta(page, "description", "name")
    assert len(meta(page, "og:title")) == 1 and meta(page, "og:title")[0]
    assert meta(page, "og:locale") == ["en_US" if english else "pt_BR"]
    assert meta(page, "og:locale:alternate") == ["pt_BR" if english else "en_US"]
    assert meta(page, "twitter:card", "name") == ["summary_large_image"]
    assert meta(page, "theme-color", "name") == [plane()]
    assert len(meta(page, "og:image:alt")) == 1 and meta(page, "og:image:alt")[0]
    image = meta(page, "og:image")
    # A reading page describes the card the way its language's landing does.
    assert meta(page, "og:image:alt") == meta(
        load("/" if english else "/pt-br/")[1], "og:image:alt"
    )
    assert image == [f"{ORIGIN}/img/og-{'en' if english else 'pt-br'}.png"]
    png = (SITE / urlsplit(image[0]).path.lstrip("/")).read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and png[12:16] == b"IHDR"
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (1200, 630)
    assert (meta(page, "og:image:width"), meta(page, "og:image:height")) == (["1200"], ["630"])


def catalogue_strings(lang: str) -> list[str]:
    """Every string the dashboard and the desktop shell show, in one language."""

    def walk(node) -> list[str]:
        if isinstance(node, dict):
            return [s for value in node.values() for s in walk(value)]
        return [node] if isinstance(node, str) else []

    files = sorted((ROOT / "web" / "src" / "locales" / lang).glob("*.json"))
    files.append(ROOT / "desktop" / "src" / "locales" / f"{lang}.json")
    return [s for f in files for s in walk(json.loads(f.read_text(encoding="utf-8")))]


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_every_app_label_is_the_apps_own_words(url_path):
    """`<b>` quotes a label the app or Arena shows, so it must match the catalogue.

    A renamed button would otherwise leave the help page naming one that no
    longer exists. Arena's own labels count because the welcome step's
    instructions quote them. Anything else set in bold, a Windows dialog or a
    warning, is `<strong>`.
    """
    _, page = load(url_path)
    lang = "en" if url_path == NOT_FOUND else PAGES[url_path][1]
    strings = catalogue_strings(lang)
    for label in page.labels:
        phrase = re.compile(rf"(?<!\w){re.escape(label)}(?!\w)")
        assert any(phrase.search(s) for s in strings), (url_path, label)


def test_the_help_pages_quote_the_app():
    for url_path in ("/help/", "/pt-br/help/"):
        _, page = load(url_path)
        assert len(page.labels) > 20, url_path
    english = load("/help/")[1].labels
    portuguese = load("/pt-br/help/")[1].labels
    assert len(english) == len(portuguese)


def test_the_404_page_has_no_card_and_keeps_its_head_bare():
    _, page = load(NOT_FOUND)
    assert not [a for a in page.find("meta") if (a.get("property") or "").startswith("og:")]
    assert not meta(page, "twitter:card", "name")
    assert not meta(page, "theme-color", "name")
    assert not meta(page, "description", "name")


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_the_header_reads_the_same_on_every_page(url_path):
    """Download, Help, Privacy, Donate: the landing's header, the same four targets site-wide."""
    raw, _ = load(url_path)
    english = url_path == NOT_FOUND or PAGES[url_path][1] == "en"
    prefix = "" if english else "/pt-br"
    nav = Page()
    nav.feed(re.search(r"<nav>(.*?)</nav>", raw, re.S).group(1))
    assert nav.links == [
        (f"{prefix}/#download", "Download" if english else "Baixar"),
        (f"{prefix}/help/", "Help" if english else "Ajuda"),
        (f"{prefix}/#never-leaves", "Privacy" if english else "Privacidade"),
        (f"{prefix}/#donate", "Donate" if english else "Doar"),
    ]


def test_the_store_listing_is_a_button_a_step_and_a_help_line():
    for url_path in ("/", "/pt-br/"):
        raw, page = load(url_path)
        assert "STORE_URL" not in raw
        assert "Microsoft Store:" in page.visible_text
        # Three button groups and the Store step.
        assert hrefs(page).count(STORE) == 4, url_path
    for url_path in ("/help/", "/pt-br/help/"):
        _, page = load(url_path)
        assert hrefs(page).count(STORE) == 1, url_path


def test_the_policy_pages_carry_the_date_they_changed():
    """The privacy policy's date is its version, `POLICY_VERSION`, which an
    account's consent records: the two never drift apart."""
    source = (ROOT / "web" / "src" / "lib" / "policy.ts").read_text(encoding="utf-8")
    found = re.search(r"POLICY_VERSION = '(\d{4}-\d{2}-\d{2})'", source)
    assert found, "web/src/lib/policy.ts no longer declares POLICY_VERSION = 'YYYY-MM-DD'"
    for url_path in POLICY_PAGES:
        phrase = "Last changed" if PAGES[url_path][1] == "en" else "Última alteração:"
        _, page = load(url_path)
        assert f"{phrase} {found.group(1)}" in page.paragraphs, url_path


def test_the_privacy_pages_name_every_request_the_app_makes():
    for url_path in ("/privacy/", "/pt-br/privacy/"):
        _, page = load(url_path)
        text = page.visible_text
        for name in (
            "Scryfall",
            "MTGOFormatData",
            "MTG_decklistcache",
            "mtgo.com",
            "TopDeck.gg",
            "GitHub",
            "Cloudflare Web Analytics",
            "Supabase",
            "Sentry",
        ):
            assert name in text, (url_path, name)


def test_the_headers_allow_only_self_and_the_beacon():
    headers = (SITE / "_headers").read_text(encoding="utf-8")
    assert "X-Content-Type-Options: nosniff" in headers
    # The site's own pages as the Referer (`worker/language.mjs`), no other site's.
    assert "Referrer-Policy: same-origin" in headers
    csp = next(
        line.split(":", 1)[1].strip()
        for line in headers.splitlines()
        if line.strip().startswith("Content-Security-Policy:")
    )
    directives = {d.split()[0]: d.split()[1:] for d in csp.split(";") if d.strip()}
    assert directives["default-src"] == ["'none'"]
    assert directives["script-src"] == ["'self'", "https://static.cloudflareinsights.com"]
    assert directives["connect-src"] == ["'self'", "https://cloudflareinsights.com"]
    assert directives["style-src"] == ["'self'"]
    assert directives["font-src"] == ["'self'"]
    assert directives["img-src"] == ["'self'"]
    assert directives["media-src"] == ["'self'"]
    assert (SITE / "_redirects").read_text(encoding="utf-8").split() == ["/pt-br", "/pt-br/", "301"]
    assert "Allow: /" in (SITE / "robots.txt").read_text(encoding="utf-8")


def test_the_stylesheet_loads_nothing_from_elsewhere_and_uses_only_the_two_subsets():
    css = (SITE / "site.css").read_text(encoding="utf-8")
    assert "@import" not in css
    assert not re.search(r"url\(\s*['\"]?(https?:)?//", css)
    fonts = sorted(p.name for p in (SITE / "fonts").glob("*.woff2"))
    subsets = [
        "inter-latin-ext-wght-normal.woff2",
        "inter-latin-wght-normal.woff2",
    ]
    assert fonts == subsets
    assert sorted(set(re.findall(r"fonts/([\w.-]+\.woff2)", css))) == subsets
    assert sorted(p.name for p in (SITE / "fonts").glob("LICENSE-*")) == ["LICENSE-inter.txt"]
    licence = (SITE / "fonts" / "LICENSE-inter.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE" in licence.upper()


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_what_first_paint_loads_stays_under_600_kb_and_the_whole_page_under_1_mb(url_path):
    """First paint: the HTML, the stylesheet, every font, our script, the poster and eager images.

    A lazy image is fetched as it scrolls into view, so it counts toward the
    second cap only; each file counts once, however many times the page shows it.
    The video starts after first paint and has its own cap, DEMO_VIDEO_CAP, in
    `test_each_language_has_a_demo_video_under_the_cap`.
    """
    raw, page = load(url_path)
    total = len(raw.encode("utf-8")) + (SITE / "site.css").stat().st_size
    total += sum(p.stat().st_size for p in (SITE / "fonts").glob("*.woff2"))
    eager = {a["src"] for a in page.find("img") if a.get("loading") != "lazy"}
    eager |= {a["poster"] for a in page.find("video")}
    eager |= {a["src"] for a in page.find("script") if a["src"].startswith("/")}
    lazy = {a["src"] for a in page.find("img") if a.get("loading") == "lazy"} - eager
    first_paint = total + sum((SITE / src.lstrip("/")).stat().st_size for src in eager)
    whole = first_paint + sum((SITE / src.lstrip("/")).stat().st_size for src in lazy)
    assert first_paint < FIRST_PAINT_LIMIT
    assert whole < WHOLE_PAGE_LIMIT


def test_the_404_page_is_english_with_a_portuguese_paragraph_and_no_counterpart():
    _, page = load(NOT_FOUND)
    assert page.find("html")[0].get("lang") == "en"
    # The header's brand and language links point at the same two places, so
    # the body's own links are told apart by their words.
    assert ("/", "Sensei Top home") in page.links
    assert ("/pt-br/", "Página inicial") in page.links
    robots = [a for a in page.find("meta") if a.get("name") == "robots"]
    assert len(robots) == 1 and "noindex" in (robots[0].get("content") or "")
    portuguese = [t for t, a in page.tags if a.get("lang") == "pt-BR" and t == "p"]
    assert len(portuguese) == 2
    assert not [a for a in page.find("link") if a.get("rel") in ("canonical", "alternate")]


def test_the_worker_serves_site_with_its_404_page():
    """The site is a Cloudflare Worker's static assets, configured by `wrangler.json`.

    Without the file, Workers Builds generates one on every deploy, and the
    generated one answers an unknown path with an empty 404 rather than
    `404.html`.
    """
    config = json.loads((SITE.parent / "wrangler.json").read_text(encoding="utf-8"))
    assets = config["assets"]
    assert (SITE.parent / assets["directory"]).resolve() == SITE
    assert assets["not_found_handling"] == "404-page"
    assert (SITE / "404.html").is_file()


def test_the_download_buttons_go_to_the_worker_and_it_runs_only_for_them():
    """`/download/<platform>` redirects to the newest release's file (`worker/download.mjs`).

    The script runs for `/download/*`, the English pages a visitor in Brazil
    is sent from (`worker/language.mjs`) and the Portuguese home page, which
    gets the installer suggestion (`worker/suggest.mjs`); every other path is
    a static asset that never reaches it.
    """
    config = json.loads((SITE.parent / "wrangler.json").read_text(encoding="utf-8"))
    assert (SITE.parent / config["main"]).is_file()
    first = config["assets"]["run_worker_first"]
    assert first == [
        "/download/*",
        "/",
        "/help/",
        "/privacy/",
        "/terms/",
        "/untapped/",
        "/linux/",
        "/mtgo/",
        "/pt-br/",
        "/video/*",
    ]
    # `/video/*` stays: static assets ignore Range (`worker/range.mjs`).
    assert set(first) == {"/download/*", *portuguese_redirects(), "/pt-br/", "/video/*"}
    assert config["assets"]["binding"] == "ASSETS"
    assert config["observability"] == {"enabled": False}
    for url_path in ("/", "/pt-br/"):
        _, page = load(url_path)
        buttons = [a["href"] for a in page.find("a") if "button" in (a.get("class") or "").split()]
        # The hero, under the "download" heading, and before the footer.
        assert buttons == [STORE, "/download/linux", "/download/windows"] * 3, url_path
        assert not [h for h in hrefs(page) if "/releases" in h], url_path


@pytest.mark.parametrize("url_path", ["/help/", "/pt-br/help/"])
def test_each_help_page_links_the_tarball_once(url_path):
    _, page = load(url_path)
    assert hrefs(page).count(TARBALL) == 1, url_path


@pytest.mark.parametrize("url_path", LANDINGS)
def test_no_landing_links_the_tarball(url_path):
    _, page = load(url_path)
    assert TARBALL not in hrefs(page), url_path


@pytest.mark.parametrize("url_path", LANDINGS)
def test_each_landing_carries_one_hidden_note_per_system_with_no_build(url_path):
    _, page = load(url_path)
    notes = [a for a in page.find("p") if "data-os" in a]
    assert all("hidden" in a for a in notes), url_path
    assert sorted(a["data-os"] for a in notes) == ["mac", "phone"], url_path


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_static_buttons_keep_windows_first_for_an_unknown_visitor(url_path):
    _, page = load(url_path)
    buttons = [a for a in page.find("a") if "button" in (a.get("class") or "").split()]
    assert [(a["href"], a["class"]) for a in buttons] == [
        (STORE, "button primary"),
        ("/download/linux", "button"),
        ("/download/windows", "button quiet"),
    ] * 3, url_path


def test_the_stylesheet_puts_the_primary_button_first():
    css = (SITE / "site.css").read_text(encoding="utf-8")
    assert ".actions .primary { order: -1; }" in css


def test_the_sitemap_lists_every_page_with_its_other_language():
    """`sitemap.xml` names each page once, with the same pair its own head names."""
    import xml.etree.ElementTree as ET

    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
    root = ET.parse(SITE / "sitemap.xml").getroot()
    listed = {}
    for url in root.findall("s:url", ns):
        loc = url.find("s:loc", ns).text
        listed[loc] = {link.get("hreflang"): link.get("href") for link in url.findall("x:link", ns)}
    assert sorted(listed) == sorted(ORIGIN + path for path in ALL_PAGES)
    for url_path in ALL_PAGES:
        _, page = load(url_path)
        own = {a["hreflang"]: a["href"] for a in page.find("link") if a.get("rel") == "alternate"}
        assert listed[ORIGIN + url_path] == own, url_path
    robots = (SITE / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {ORIGIN}/sitemap.xml" in robots.splitlines()


def test_every_page_is_linked_from_the_landing_in_its_language():
    """A page only the sitemap names is one a reader never finds."""
    for landing in LANDINGS:
        _, page = load(landing)
        lang = PAGES[landing][1]
        for url_path, (_, page_lang, _) in PAGES.items():
            if page_lang == lang and url_path != landing:
                assert url_path in hrefs(page), (landing, url_path)


def portuguese_redirects():
    """`PORTUGUESE` in `worker/language.mjs`: English path -> Portuguese path."""
    return dict(
        re.findall(
            r"'(/[^']*)': '(/pt-br/[^']*)'",
            (SITE.parent / "worker" / "language.mjs").read_text(encoding="utf-8"),
        )
    )


def test_a_visitor_in_brazil_is_sent_from_every_english_page_to_its_portuguese_one():
    """The privacy pages promise the redirect for every English page with a Portuguese version."""
    english = {path: other for path, (_, lang, other) in PAGES.items() if lang == "en"}
    assert portuguese_redirects() == english


def test_the_worker_script_passes_its_own_tests():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "--test", "worker/*.test.mjs"],
        cwd=SITE.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def demo_shots() -> list[dict]:
    """The product shots of the video's one timeline, in order."""
    shots = json.loads((ROOT / "scripts/demo-video/shots.json").read_text(encoding="utf-8"))
    return [shot for shot in shots if shot["kind"] == "video"]


def demo_times() -> tuple[list[tuple[float, float]], float]:
    """Each shot's (start, end) and the length, from the lengths alone.

    Each 0.3 s crossfade eats that much from a join. A shot has started once
    the fade into it has finished, and it ends where the next one's begins.
    """
    shots = demo_shots()
    fades = [sum(s["seconds"] - DEMO_FADE for s in shots[:i]) for i in range(len(shots))]
    total = fades[-1] + shots[-1]["seconds"]
    starts = [0.0, *[fade + DEMO_FADE for fade in fades[1:]]]
    return list(zip(starts, [*fades[1:], total], strict=True)), total


def demo_chapter_list(lang: str) -> dict:
    return json.loads((SITE / "video" / f"demo-{lang}.chapters.json").read_text(encoding="utf-8"))


def demo_video_length(lang: str) -> float:
    """The file's own length where ffprobe is there, otherwise the chapter list's."""
    if shutil.which("ffprobe") is None:
        return demo_chapter_list(lang)["duration"]
    probe = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
    path = str(SITE / "video" / f"demo-{lang}.mp4")
    return float(subprocess.run([*probe, path], check=True, capture_output=True, text=True).stdout)


def parse_vtt(text: str) -> list[tuple[float, float, str]]:
    """(start, end, text) per cue. Anything but this file's plain shape fails here."""
    header, *blocks = text.strip().split("\n\n")
    assert header == "WEBVTT"
    stamp = r"(\d\d):(\d\d):(\d\d)\.(\d{3})"
    cues = []
    for block in blocks:
        _, timing, *lines = block.split("\n")
        found = re.fullmatch(f"{stamp} --> {stamp}", timing)
        assert found, timing
        h0, m0, s0, ms0, h1, m1, s1, ms1 = (int(part) for part in found.groups())
        start = h0 * 3600 + m0 * 60 + s0 + ms0 / 1000
        end = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        cues.append((start, end, " ".join(lines)))
    return cues


@pytest.mark.parametrize("lang", DEMO_VIDEOS)
def test_each_language_has_a_demo_video_under_the_cap(lang):
    video = SITE / "video" / f"demo-{lang}.mp4"
    assert video.is_file()
    assert video.stat().st_size < DEMO_VIDEO_CAP


@pytest.mark.parametrize("lang", DEMO_VIDEOS)
def test_the_demo_video_starts_as_it_downloads_and_runs_the_timeline(lang):
    """The index comes before the media, one H.264 stream, nothing to hear."""
    video = SITE / "video" / f"demo-{lang}.mp4"
    atoms = []
    with video.open("rb") as stream:
        while len(head := stream.read(8)) == 8:
            size, name = struct.unpack(">I4s", head)
            atoms.append(name)
            if size == 1:
                size = struct.unpack(">Q", stream.read(8))[0] - 8
            stream.seek(size - 8, 1)
    assert atoms.index(b"moov") < atoms.index(b"mdat")
    assert abs(demo_video_length(lang) - demo_times()[1]) < 0.2
    if shutil.which("ffprobe") is None:
        return
    streams = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,pix_fmt",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert json.loads(streams)["streams"] == [{"codec_name": "h264", "pix_fmt": "yuv420p"}]


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="needs ffprobe")
@pytest.mark.parametrize("lang", DEMO_VIDEOS)
def test_the_demo_video_is_tagged_bt709_and_seeks_to_each_chapter(lang):
    """An untagged file shifts the palette; a chapter off a keyframe seeks late."""
    video = str(SITE / "video" / f"demo-{lang}.mp4")
    tags = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=color_space,color_primaries,color_transfer",
            "-of",
            "json",
            video,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    (stream,) = json.loads(tags)["streams"]
    assert stream == {
        "color_space": "bt709",
        "color_primaries": "bt709",
        "color_transfer": "bt709",
    }
    keyframes = [
        float(line)
        for line in subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-skip_frame",
                "nokey",
                "-select_streams",
                "v",
                "-show_entries",
                "frame=pts_time",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
    ]
    for chapter in demo_chapter_list(lang)["chapters"]:
        assert any(abs(key - chapter["start"]) < 0.02 for key in keyframes), chapter["id"]


def first_frame_ground(path: Path, matrix: str) -> tuple[int, ...]:
    """The darkest of a first frame's two commonest colours, read as `matrix`, limited range."""
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale=in_color_matrix={matrix}:in_range=tv:out_range=pc:flags=accurate_rnd,"
            "format=rgb24",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    pixels = Counter(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
    return min((colour for colour, _ in pixels.most_common(2)), key=sum)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
@pytest.mark.parametrize("lang", DEMO_VIDEOS)
def test_the_video_opens_in_the_posters_colours(lang):
    """The video replaces the poster in place: a shifted ground shows as a flash."""
    _, name = DEMO_VIDEOS[lang]
    video = first_frame_ground(SITE / "video" / f"demo-{lang}.mp4", "bt709")
    poster = first_frame_ground(SITE / "img" / name, "bt601")
    assert all(abs(a - b) <= 2 for a, b in zip(video, poster, strict=True)), (video, poster)


@pytest.mark.parametrize("lang", DEMO_VIDEOS)
def test_the_captions_parse_fit_the_video_and_carry_the_supplied_words(lang):
    shots = demo_shots()
    if lang == "en":
        words = [shot["caption"] for shot in shots]
    else:
        source = ROOT / "scripts/demo-video" / f"shots.{lang}.json"
        supplied = json.loads(source.read_text(encoding="utf-8"))
        assert list(supplied) == [shot["id"] for shot in shots]
        words = list(supplied.values())
    vtt = (SITE / "video" / f"demo-{lang}.vtt").read_text(encoding="utf-8")
    cues = parse_vtt(vtt)
    times, _ = demo_times()
    assert [cue[2] for cue in cues] == words
    assert [cue[0] for cue in cues] == pytest.approx([t[0] for t in times], abs=0.002)
    assert [cue[1] for cue in cues] == pytest.approx([t[1] for t in times], abs=0.002)
    length = demo_video_length(lang)
    assert all(0 <= start < end <= length + 0.05 for start, end, _ in cues)


@pytest.mark.parametrize("lang", DEMO_VIDEOS)
def test_the_chapters_start_where_each_shot_shows_and_use_the_apps_words(lang):
    listed = demo_chapter_list(lang)
    times, total = demo_times()
    assert listed["duration"] == pytest.approx(total, abs=0.002)
    chapters = listed["chapters"]
    assert [c["id"] for c in chapters] == [shot["id"] for shot in demo_shots()]
    assert [c["start"] for c in chapters] == pytest.approx([t[0] for t in times], abs=0.002)
    catalogue, _ = DEMO_VIDEOS[lang]
    words = catalogue_strings(catalogue)
    assert all(c["label"] in words for c in chapters)
    for chapter in chapters:
        namespace, *path = DEMO_CHAPTER_KEYS[chapter["id"]]
        node = json.loads(
            (ROOT / "web" / "src" / "locales" / catalogue / f"{namespace}.json").read_text(
                encoding="utf-8"
            )
        )
        for part in path:
            node = node[part]
        assert chapter["label"] == node, chapter["id"]


@pytest.mark.parametrize("lang", DEMO_VIDEOS)
def test_the_demo_poster_is_small_enough_for_first_paint(lang):
    _, name = DEMO_VIDEOS[lang]
    poster = SITE / "img" / name
    assert poster.is_file()
    head = poster.read_bytes()[:12]
    assert head[:4] == b"RIFF" and head[8:] == b"WEBP"
    assert poster.stat().st_size < DEMO_POSTER_LIMIT


@pytest.mark.parametrize("catalogue", [folder for folder, _ in DEMO_VIDEOS.values()])
def test_every_label_the_recording_looks_for_is_in_the_catalogue(catalogue):
    """record.ts finds a shot's targets by these; a key that left stops a take."""
    script = (ROOT / "scripts/demo-video/record.ts").read_text(encoding="utf-8")
    keys = re.findall(r"\blabel\('([\w.]+)'", script)
    assert keys
    for key in keys:
        namespace, *path = key.split(".")
        locale = ROOT / "web/src/locales" / catalogue / f"{namespace}.json"
        node = json.loads(locale.read_text(encoding="utf-8"))
        for part in path:
            node = node[part]
        assert isinstance(node, str), key
