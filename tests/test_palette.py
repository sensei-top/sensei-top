"""scripts/validate_palette.py, loaded by path the way test_privacy_scan.py
loads its own script (`importlib.util.spec_from_file_location`) -- it lives
outside `src/sensei_top` and is never imported as a package.

The palette is declared in three places that cannot share one import: the
script (Python, checked here), `web/src/index.css` (CSS custom properties,
recharts cannot resolve `var()`), and `web/src/theme.ts` (the same values as
literal hex strings, for recharts). Nothing at build time keeps them in
step -- this suite is that check, read straight from the two frontend files'
own text rather than a value copied out of a run (AGENTS.md rule 8): a
future edit to any one of the three without the other two now fails here
instead of silently drifting until someone notices a chart's colour doesn't
match its legend.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "validate_palette.py"
INDEX_CSS = REPO_ROOT / "web" / "src" / "index.css"
THEME_TS = REPO_ROOT / "web" / "src" / "theme.ts"


def _load_script():
    spec = importlib.util.spec_from_file_location("validate_palette_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_palette_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _css_root_vars() -> dict[str, str]:
    """The first `:root { ... }` block's custom properties, name (without
    the leading `--`) to raw value. index.css declares every token this
    phase cares about there, before the density/compact-viewport overrides
    that follow it re-open `:root` for a narrower set."""
    text = INDEX_CSS.read_text()
    match = re.search(r":root \{(.*?)\n\}", text, re.S)
    assert match, "index.css has no :root block to read tokens from"
    return {
        name: value.strip()
        for name, value in re.findall(r"--([a-zA-Z0-9-]+):\s*([^;]+);", match.group(1))
    }


def _theme_dark() -> dict[str, str]:
    """`theme.ts`'s `DARK` object, member name to its literal hex string."""
    text = THEME_TS.read_text()
    match = re.search(r"const DARK: Tokens = \{(.*?)\n\}", text, re.S)
    assert match, "theme.ts has no `const DARK: Tokens = { ... }` to read"
    return dict(re.findall(r"(\w+):\s*'([^']+)'", match.group(1)))


def test_main_returns_0():
    module = _load_script()
    assert module.main() == 0


def test_main_prints_the_four_new_section_headings(capsys):
    """The four hard-fail sections this phase added (`inputs/phase-1a-
    wording.md`'s own strings, not a value copied from a run) each print
    their heading -- so a deleted section fails here rather than only
    showing up as a missing PASS line nobody reads."""
    module = _load_script()
    module.main()
    out = capsys.readouterr().out

    headings = [
        "-- accent on every surface: >= 4.5 (it is used as text) --",
        "-- on-accent text on an accent fill: >= 4.5 --",
        "-- accent vs every data colour: CIE76 ΔE >= 20 under normal vision "
        "and every CVD sim (hard fail) --",
        "-- tinted pills: win / loss / warn on their own 12% tint, "
        "over plane, surface-1 and surface-2: >= 4.5 --",
    ]
    for heading in headings:
        assert heading in out, f"main()'s output is missing: {heading}"


def test_every_script_colour_matches_index_css():
    """Every hex the script declares (surfaces, text, lines, series, status,
    mana, plus the accent pair and the mana glyph) has the identical hex
    under the same `--name` custom property in index.css's :root block --
    the property this whole suite exists to pin, read from both files'
    own text rather than from a script run."""
    module = _load_script()
    css_vars = _css_root_vars()

    # SERIES keys carry a "(self)"/"(opponent)"/"(field)" annotation the CSS
    # variable name doesn't; strip it before mapping to --series-N.
    series = {name.split(" ")[0]: hex_value for name, hex_value in module.SERIES.items()}

    expected: dict[str, str] = {
        **module.SURFACES,
        **module.TEXT,
        **module.LINES,
        **series,
        **module.STATUS,
        **module.MANA,
        "accent": module.ACCENT,
        "on-accent": module.ON_ACCENT,
        "mana-glyph": module.MANA_GLYPH,
    }

    for name, hex_value in expected.items():
        assert name in css_vars, f"index.css's :root has no --{name}"
        assert css_vars[name].lower() == hex_value.lower(), (
            f"--{name}: index.css has {css_vars[name]}, script has {hex_value}"
        )


def test_theme_ts_dark_agrees_with_the_script():
    """`theme.ts`'s `DARK` is recharts' own copy of the same palette --
    checked member by member against the script rather than against
    index.css directly, since a couple of names map differently (`grid`/
    `axis` are the two line tokens, `surface` is surface-1, `ink2` is
    ink-2)."""
    module = _load_script()
    dark = _theme_dark()

    assert dark["self"] == module.SERIES["series-1 (self)"]
    assert dark["opponent"] == module.SERIES["series-2 (opponent)"]
    assert dark["field"] == module.SERIES["series-3 (field)"]
    assert dark["grid"] == module.LINES["line"]
    assert dark["axis"] == module.LINES["line-2"]
    assert dark["surface"] == module.SURFACES["surface-1"]
    assert dark["muted"] == module.TEXT["muted"]
    assert dark["ink"] == module.TEXT["ink"]
    assert dark["ink2"] == module.TEXT["ink-2"]


def test_pill_tint_is_12_percent():
    """The 12% tint index.css's own comment describes for a result pill is
    never parsed out of that comment -- fragile, and not the source of
    truth. It is pinned here directly against the script's own constant,
    which is what the "tinted pills" hard-fail section in main() actually
    uses."""
    module = _load_script()
    assert module.PILL_TINT == 0.12
