"""The static site in `site/` keeps the promises its own copy makes.

Five hand-written pages, no build step (`docs/frontend.md`, "The site"). The
checks read the HTML with the standard library's parser: the pages are small
enough that a structural slip (a second script, a refresh, a link to the wrong
repository, a drifted Fan Content notice) is the realistic failure, and none of
it shows in a browser until a visitor meets it.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from test_attribution import WIZARDS_NOTICE

SITE = Path(__file__).resolve().parents[1] / "site"
ORIGIN = "https://senseitop.com"
PROJECT = "https://github.com/sensei-top/sensei-top"
BEACON_SRC = "https://static.cloudflareinsights.com/beacon.min.js"

# url path -> (file, html lang, the path of the same page in the other language)
PAGES = {
    "/": ("index.html", "en", "/pt-br/"),
    "/privacy/": ("privacy/index.html", "en", "/pt-br/privacy/"),
    "/pt-br/": ("pt-br/index.html", "pt-BR", "/"),
    "/pt-br/privacy/": ("pt-br/privacy/index.html", "pt-BR", "/privacy/"),
}
ALL_PAGES = list(PAGES)
# The 404 page is one page in both languages: no counterpart, no hreflang pair,
# no description meta. It is in every list the shell pages share and out of
# the ones about language and the head.
NOT_FOUND = "/404.html"
SHELL_PAGES = [*ALL_PAGES, NOT_FOUND]
PAGE_WEIGHT_LIMIT = 600 * 1024


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

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag == "a" and attributes.get("href"):
            self._link = (attributes["href"], [])
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        if tag == "p":
            self._paragraph = []
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
        if tag == "script":
            self._in_script = False
        if tag in ("script", "style", "title"):
            self._skip -= 1

    def handle_data(self, data):
        if self._link is not None:
            self._link[1].append(data)
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
    _, page = load(url_path)
    viewport = [a for a in page.find("meta") if a.get("name") == "viewport"]
    description = [a for a in page.find("meta") if a.get("name") == "description"]
    assert len(viewport) == 1
    assert len(description) == 1 and description[0]["content"]


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
    references = [h for h in hrefs(page) if h.startswith("/")]
    references += [a["src"] for a in page.find("img")]
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
        assert f"{phrase} 2026-10-12" in page.paragraphs


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
    assert "Referrer-Policy: no-referrer" in headers
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
def test_a_page_with_everything_it_loads_stays_under_600_kb(url_path):
    raw, page = load(url_path)
    total = len(raw.encode("utf-8")) + (SITE / "site.css").stat().st_size
    total += sum(p.stat().st_size for p in (SITE / "fonts").glob("*.woff2"))
    for img in page.find("img"):
        total += (SITE / img["src"].lstrip("/")).stat().st_size
    assert total < PAGE_WEIGHT_LIMIT


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
