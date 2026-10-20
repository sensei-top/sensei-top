"""The static site in `site/` keeps the promises its own copy makes.

Seven hand-written pages, no build step (`docs/frontend-site.md`, "The site"). The
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
# Answered by the Worker script in `worker/`, not by a file under `site/`.
DOWNLOADS = ("/download/windows", "/download/linux")

# url path -> (file, html lang, the path of the same page in the other language)
PAGES = {
    "/": ("index.html", "en", "/pt-br/"),
    "/privacy/": ("privacy/index.html", "en", "/pt-br/privacy/"),
    "/pt-br/": ("pt-br/index.html", "pt-BR", "/"),
    "/pt-br/privacy/": ("pt-br/privacy/index.html", "pt-BR", "/privacy/"),
    "/help/": ("help/index.html", "en", "/pt-br/help/"),
    "/pt-br/help/": ("pt-br/help/index.html", "pt-BR", "/help/"),
}
ALL_PAGES = list(PAGES)
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
# The pages whose head carries the Open Graph card: all six, never the 404.
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
    raw, _ = load(url_path)
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
    assert len(scripts) == 1
    script = scripts[0]
    assert script["src"] == BEACON_SRC
    assert "defer" in script
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
    references = [h for h in hrefs(page) if h.startswith("/") and h not in DOWNLOADS]
    references += [own + h for h in hrefs(page) if h.startswith("#")]
    references += [a["src"] for a in page.find("img")]
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
    _, page = load(url_path)
    images = [a for a in page.find("img") if a["src"] != "/img/mark.svg"]
    eager = [a for a in images if a.get("loading") != "lazy"]
    assert len(eager) == 1
    # The first content image in the document, so a lazy hero beside an eager
    # Home row fails.
    assert eager[0] is images[0]
    assert eager[0]["src"] == ("/img/home.webp" if url_path == "/" else "/img/pt-br/home.webp")
    assert eager[0].get("fetchpriority") == "high"
    for img in images:
        if img is not eager[0]:
            assert img.get("loading") == "lazy", img["src"]
            assert "fetchpriority" not in img
        assert (img["width"], img["height"]) == ("1440", "900"), img["src"]


@pytest.mark.parametrize("url_path", LANDINGS)
def test_the_landing_preloads_the_two_latin_fonts_the_stylesheet_uses(url_path):
    _, page = load(url_path)
    css = (SITE / "site.css").read_text(encoding="utf-8")
    preloads = [a for a in page.find("link") if a.get("rel") == "preload"]
    assert sorted(a["href"] for a in preloads) == [
        "/fonts/bricolage-grotesque-latin-wght-normal.woff2",
        "/fonts/hanken-grotesk-latin-wght-normal.woff2",
    ]
    for link in preloads:
        assert link["as"] == "font" and link["type"] == "font/woff2"
        assert "crossorigin" in link
        assert link["href"].removeprefix("/") in css


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


def test_the_store_line_waits_in_a_comment_for_its_listing():
    for url_path in ("/", "/pt-br/"):
        raw, page = load(url_path)
        assert "STORE_URL" not in hrefs(page)
        assert "STORE_URL" not in page.visible_text
        commented = [c for c in page.comments if "STORE_URL" in c]
        assert len(commented) == 1
        assert "Microsoft Store:" in commented[0]
        assert raw.count("STORE_URL") == commented[0].count("STORE_URL")


def test_the_privacy_pages_carry_the_date_they_changed():
    phrases = {"/privacy/": "Last changed", "/pt-br/privacy/": "Última alteração:"}
    for url_path, phrase in phrases.items():
        _, page = load(url_path)
        assert f"{phrase} 2026-10-19" in page.paragraphs


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
    assert (SITE / "_redirects").read_text(encoding="utf-8").split() == ["/pt-br", "/pt-br/", "301"]
    assert "Allow: /" in (SITE / "robots.txt").read_text(encoding="utf-8")


def test_the_stylesheet_loads_nothing_from_elsewhere_and_uses_only_the_two_subsets():
    css = (SITE / "site.css").read_text(encoding="utf-8")
    assert "@import" not in css
    assert not re.search(r"url\(\s*['\"]?(https?:)?//", css)
    fonts = sorted(p.name for p in (SITE / "fonts").glob("*.woff2"))
    assert fonts == [
        "bricolage-grotesque-latin-ext-wght-normal.woff2",
        "bricolage-grotesque-latin-wght-normal.woff2",
        "hanken-grotesk-latin-ext-wght-normal.woff2",
        "hanken-grotesk-latin-wght-normal.woff2",
    ]
    for font in fonts:
        assert f"fonts/{font}" in css
    for family in ("bricolage-grotesque", "hanken-grotesk"):
        licence = (SITE / "fonts" / f"LICENSE-{family}.txt").read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in licence.upper()


@pytest.mark.parametrize("url_path", SHELL_PAGES)
def test_what_first_paint_loads_stays_under_600_kb_and_the_whole_page_under_1_mb(url_path):
    """First paint: the HTML, the stylesheet, every font and each image not marked lazy.

    A lazy image is fetched as it scrolls into view, so it counts toward the
    second cap only; each file counts once, however many times the page shows it.
    """
    raw, page = load(url_path)
    total = len(raw.encode("utf-8")) + (SITE / "site.css").stat().st_size
    total += sum(p.stat().st_size for p in (SITE / "fonts").glob("*.woff2"))
    eager = {a["src"] for a in page.find("img") if a.get("loading") != "lazy"}
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
    assert first == ["/download/*", "/", "/help/", "/privacy/", "/pt-br/"]
    assert set(first) == {"/download/*", *portuguese_redirects(), "/pt-br/"}
    assert config["assets"]["binding"] == "ASSETS"
    assert config["observability"] == {"enabled": False}
    for url_path in ("/", "/pt-br/"):
        _, page = load(url_path)
        buttons = [a["href"] for a in page.find("a") if "button" in (a.get("class") or "").split()]
        assert buttons == list(DOWNLOADS), url_path
        assert not [h for h in hrefs(page) if "/releases" in h], url_path


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
        ("/download/windows", "button primary"),
        ("/download/linux", "button"),
    ], url_path


def test_the_stylesheet_puts_the_primary_button_first():
    css = (SITE / "site.css").read_text(encoding="utf-8")
    assert ".actions .primary { order: -1; }" in css


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
