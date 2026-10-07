"""Attribution stays in step across the three places that carry it.

Wizards' Fan Content Policy notice appears in `README.md`,
`docs/attribution.md` and the dashboard (`web/src/credits.ts`), and every
outside source `docs/attribution.md` lists must also be credited in the
dashboard's credits view (the document's own rule 3). Nothing else checks
either: `web/` has no test runner, and a drifted notice or a missing credit
renders without complaint.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
ATTRIBUTION = REPO_ROOT / "docs" / "attribution.md"
CREDITS = REPO_ROOT / "web" / "src" / "credits.ts"

# Ground truth is Wizards' own notice as fetched from the Fan Content Policy
# page (kept outside the repository), with its "[Title of your Fan Content]"
# placeholder replaced by this project's name. Not read from any file under
# test, so a copy that drifts cannot also move the expectation.
WIZARDS_NOTICE = "Sensei Top is unofficial Fan Content permitted under the Fan Content Policy. Not approved/endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast. ©Wizards of the Coast LLC."  # noqa: E501

# The rows docs/attribution.md carries today. Minimums, not exact counts: a new
# source must not break this test, but a parser that finds nothing must.
MIN_SOURCES = 5
MIN_FONTS = 3

_LINK_TEXT = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CREDIT_NAME = re.compile(r"""\bname:\s*(['"])(.+?)\1""")


def has_notice_line(text: str) -> bool:
    """One whole line is exactly the notice (Markdown files)."""
    return WIZARDS_NOTICE in text.splitlines()


_STRING_LITERAL = re.compile(r"""^\s*(['"])(.*)\1\s*;?\s*$""")


def wizards_notice_value(typescript: str) -> str | None:
    """The one-line string literal assigned to `export const wizardsNotice`,
    on the declaration's own line or the next, whichever the formatter chose.
    The value itself, not any line that happens to contain the sentence: a
    copy in a comment must not keep this green while the export drifts."""
    lines = typescript.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("export const wizardsNotice"):
            continue
        _, _, rest = line.partition("=")
        if not rest.strip() and index + 1 < len(lines):
            rest = lines[index + 1]
        match = _STRING_LITERAL.match(rest)
        return match.group(2) if match else None
    return None


def table_names(markdown: str, heading: str) -> list[str]:
    """The link text in the first cell of every body row of the table under
    `## {heading}`. A row whose first cell carries no link is an error, not a
    skip, so a malformed row can't drop out of the check unnoticed."""
    lines = markdown.splitlines()
    start = lines.index(f"## {heading}")
    section: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        section.append(line)
    rows = [line for line in section if line.startswith("|")]
    names = []
    for row in rows[2:]:  # the header row, then the |---| separator
        first_cell = row.strip("|").split("|")[0]
        match = _LINK_TEXT.search(first_cell)
        assert match, f"no linked name in the first cell of {heading!r} row: {row!r}"
        names.append(match.group(1).strip())
    return names


def credit_names(typescript: str) -> list[str]:
    """Every `name:` string value in credits.ts."""
    return [match.group(2) for match in _CREDIT_NAME.finditer(typescript)]


def missing_names(names: list[str], credited: list[str]) -> list[str]:
    """The names no credits.ts `name` carries as a whole word or phrase
    ("Mana" is carried by "Mana, by Andrew Gioia")."""
    return [
        name
        for name in names
        if not any(re.search(rf"(?<!\w){re.escape(name)}(?!\w)", c) for c in credited)
    ]


# --- Wizards' notice ---


def test_readme_carries_the_notice_on_one_line():
    assert has_notice_line(README.read_text(encoding="utf-8"))


def test_attribution_doc_carries_the_notice_on_one_line():
    assert has_notice_line(ATTRIBUTION.read_text(encoding="utf-8"))


def test_credits_module_exports_the_notice_on_one_line():
    assert wizards_notice_value(CREDITS.read_text(encoding="utf-8")) == WIZARDS_NOTICE


# --- every documented source is credited in the dashboard ---


def test_attribution_tables_parse_to_at_least_todays_rows():
    """Guards the two tests below against passing on an empty parse."""
    doc = ATTRIBUTION.read_text(encoding="utf-8")
    assert len(table_names(doc, "Sources")) >= MIN_SOURCES
    assert len(table_names(doc, "Fonts and symbols")) >= MIN_FONTS


def test_every_documented_source_is_credited():
    doc = ATTRIBUTION.read_text(encoding="utf-8")
    credited = credit_names(CREDITS.read_text(encoding="utf-8"))
    missing = missing_names(table_names(doc, "Sources"), credited)
    assert not missing, f"named in docs/attribution.md but not in web/src/credits.ts: {missing}"


def test_every_documented_font_and_symbol_set_is_credited():
    doc = ATTRIBUTION.read_text(encoding="utf-8")
    credited = credit_names(CREDITS.read_text(encoding="utf-8"))
    missing = missing_names(table_names(doc, "Fonts and symbols"), credited)
    assert not missing, f"named in docs/attribution.md but not in web/src/credits.ts: {missing}"
