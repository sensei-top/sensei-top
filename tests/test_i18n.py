"""The backend's translation layer (``i18n.py``), the request-language
middleware (``api/app.py``), the ``.pot`` extractor
(``scripts/i18n_extract.py``). The rule the whole layer exists to keep,
**every prompt is English**, whatever language the request asked for, is
tested in ``tests/ai/test_i18n_prompts.py``, which needs ``ai/``.

Expectations come from the spec, not from running the code: the
language rule (``pt-BR``/``pt*`` is Portuguese, anything else English),
gettext's own contract (a missing entry is the msgid; fuzzy entries are not
translations), and Portuguese's plural rule (``nplurals=2; plural=(n > 1)``,
so 0 takes the singular).

**The marker catalogue** is how the prompt tests stay meaningful as strings
get wrapped: it maps every msgid in the shipped ``.pot`` — plus ``PROBE``,
a test-only msgid — to ``MARKER`` + the English. A prompt fetched under
``pt-BR`` with it installed must never contain ``MARKER``. While the
``.pot`` is empty only ``PROBE`` can carry it, so the route tests below
inject ``PROBE`` where the code would put a translated string; once a phase
wraps real strings, the same tests catch a real one leaking — through a
builder without ``english()``, an object built before the builder ran, or
a cache warmed by a page under ``pt-BR``.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import sys
from pathlib import Path

import polib
import pytest
from fastapi import FastAPI

from sensei_top import i18n
from sensei_top.api import create_app
from sensei_top.api.app import RequestLanguage
from sensei_top.api.convert import _list_diff_out
from sensei_top.api.guard import LoopbackGuard
from sensei_top.db import open_database
from sensei_top.guide import rcq as guide_rcq
from sensei_top.guide.list_diff import DuplicateNames, ListDiff
from sensei_top.metagame.tiers import TIER_WORDS, TIERS, tier_words
from sensei_top.projector.matches import project
from sensei_top.reader.ingest import ingest_file
from sensei_top.review.position import SWING_DECISIVE, SWING_NOTABLE, swing_words

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "i18n_extract.py"
POT = REPO / "src" / "sensei_top" / "locale" / "sensei_top.pot"
FIXTURE = Path(__file__).parent / "fixtures" / "match_session.log"
# The fixture's one completed match (tests/ai/test_llm.py uses the same id).
MATCH_WIN = "fa7a4d16-afb7-4094-bae2-111092fc71d2"
PT_BR_PLURALS = "nplurals=2; plural=(n > 1);"

PROBE = "i18n test probe: this sentence is never in the product"
MARKER = "[pt-BR marker] "


def _load_extractor():
    spec = importlib.util.spec_from_file_location("i18n_extract_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["i18n_extract_under_test"] = module
    spec.loader.exec_module(module)
    return module


extractor = _load_extractor()


def _write_po(locale_dir: Path, language: str, entries: list[polib.POEntry], *,
              plural_forms: str = PT_BR_PLURALS) -> Path:
    po = polib.POFile()
    po.metadata = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Plural-Forms": plural_forms,
    }
    for entry in entries:
        po.append(entry)
    path = locale_dir / language / "LC_MESSAGES" / "sensei_top.po"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(po), encoding="utf-8")
    return path


@pytest.fixture
def catalogues(tmp_path):
    """Load catalogues from a ``locale`` directory under ``tmp_path``
    instead of the shipped one; the shipped set comes back afterwards."""
    locale_dir = tmp_path / "locale"
    locale_dir.mkdir()
    yield locale_dir
    i18n.load_catalogues()


@pytest.fixture
def no_catalogues(catalogues):
    """No catalogue for any language: the state a missing or broken ``.po``
    falls back to."""
    i18n.load_catalogues(catalogues)
    return catalogues


@pytest.fixture
def marker_catalogue(catalogues):
    """A PT-BR catalogue translating every ``.pot`` msgid, and ``PROBE``, to
    ``MARKER`` + the English (the module docstring says why)."""
    entries = [polib.POEntry(msgid=PROBE, msgstr=MARKER + PROBE)]
    for template in polib.pofile(str(POT)):
        if template.msgid_plural:
            entries.append(polib.POEntry(
                msgid=template.msgid, msgid_plural=template.msgid_plural,
                msgstr_plural={0: MARKER + template.msgid, 1: MARKER + template.msgid_plural},
            ))
        else:
            entries.append(polib.POEntry(msgid=template.msgid, msgstr=MARKER + template.msgid))
    _write_po(catalogues, i18n.PT_BR, entries)
    i18n.load_catalogues(catalogues)
    with i18n.use_language("pt-BR"):
        assert i18n._(PROBE) == MARKER + PROBE, "the marker catalogue did not load"
    return catalogues


# --- negotiating the language ---------------------------------------------


@pytest.mark.parametrize("header", [
    None, "", "en", "en-US", "fr", "fr-FR, de;q=0.8", "*",
    ";;,,", "pt;q=abc", "pt;q=0", "en-US, pt-BR", "en;q=0.9, pt;q=0.8", "pt;q=1.5",
])
def test_anything_but_portuguese_is_english(header):
    assert i18n.language_for(header) == i18n.ENGLISH


@pytest.mark.parametrize("header", [
    "pt-BR", "pt", "pt-PT", "PT-br", "pt_BR", "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "fr, pt;q=0.5", "en;q=0.5, pt-BR;q=0.9", "de, pt-BR;q=0.1",
])
def test_any_portuguese_tag_it_prefers_is_pt_br(header):
    assert i18n.language_for(header) == i18n.PT_BR


def test_use_language_is_scoped_and_english_overrides_it():
    assert i18n.current_language() == i18n.ENGLISH
    with i18n.use_language("pt-BR") as chosen:
        assert chosen == i18n.PT_BR
        assert i18n.current_language() == i18n.PT_BR
        with i18n.english():
            assert i18n.current_language() == i18n.ENGLISH
        assert i18n.current_language() == i18n.PT_BR

        @i18n.english()
        def builder():
            return i18n.current_language()

        assert builder() == i18n.ENGLISH
        assert builder() == i18n.ENGLISH, "a decorated builder's scope must be fresh each call"
        assert i18n.current_language() == i18n.PT_BR
    assert i18n.current_language() == i18n.ENGLISH


# --- catalogues ------------------------------------------------------------


def test_a_catalogue_translates_its_msgids_and_nothing_else(catalogues):
    _write_po(catalogues, i18n.PT_BR, [
        polib.POEntry(msgid="{n} of {total} games", msgstr="{n} de {total} jogos"),
        polib.POEntry(msgid="Fuzzy one", msgstr="Uma incerta", flags=["fuzzy"]),
        polib.POEntry(msgid="Untranslated", msgstr=""),
    ])
    assert set(i18n.load_catalogues(catalogues)) == {i18n.PT_BR}

    with i18n.use_language("pt-BR"):
        assert i18n._("{n} of {total} games").format(n=2, total=3) == "2 de 3 jogos"
        assert i18n._("Fuzzy one") == "Fuzzy one"
        assert i18n._("Untranslated") == "Untranslated"
        assert i18n._("Never extracted") == "Never extracted"
        with i18n.english():
            assert i18n._("{n} of {total} games") == "{n} of {total} games"
    assert i18n._("{n} of {total} games") == "{n} of {total} games"


def test_ngettext_follows_the_catalogues_plural_rule(catalogues):
    _write_po(catalogues, i18n.PT_BR, [polib.POEntry(
        msgid="{n} game", msgid_plural="{n} games",
        msgstr_plural={0: "{n} jogo", 1: "{n} jogos"},
    )])
    i18n.load_catalogues(catalogues)

    # English: only 1 is singular.
    assert [i18n.ngettext("{n} game", "{n} games", n) for n in (0, 1, 2)] == [
        "{n} games", "{n} game", "{n} games",
    ]
    # Portuguese: plural=(n > 1), so 0 is singular too.
    with i18n.use_language("pt-BR"):
        assert [i18n.ngettext("{n} game", "{n} games", n) for n in (0, 1, 2)] == [
            "{n} jogo", "{n} jogo", "{n} jogos",
        ]
        assert i18n.ngettext("{n} deck", "{n} decks", 0) == "{n} decks"


def test_a_missing_catalogue_is_english_and_warns_once(no_catalogues, caplog):
    with caplog.at_level(logging.WARNING, logger="sensei_top.i18n"), i18n.use_language("pt-BR"):
        assert i18n._("Opening hand") == "Opening hand"
        assert i18n.ngettext("{n} game", "{n} games", 0) == "{n} games"
        assert i18n._("Another") == "Another"
    warnings = [r for r in caplog.records if "pt_BR" in r.getMessage()]
    assert len(warnings) == 1


@pytest.mark.parametrize("content", [
    b'msgid "Opening hand"\nmsgstr "M\xc3\xa3o inicial"\nnot a po line\n',
    b'msgid "Opening hand"\nmsgstr "M\xe3o inicial"\n',  # Latin-1, not UTF-8
])
def test_a_broken_catalogue_is_english_and_warns(catalogues, caplog, content):
    path = catalogues / i18n.PT_BR / "LC_MESSAGES" / "sensei_top.po"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    with caplog.at_level(logging.WARNING, logger="sensei_top.i18n"):
        assert i18n.load_catalogues(catalogues) == {}
        with i18n.use_language("pt-BR"):
            assert i18n._("Opening hand") == "Opening hand"
    assert any("could not be read" in r.getMessage() for r in caplog.records)


def test_a_catalogue_for_a_language_the_server_does_not_speak_is_ignored(catalogues, caplog):
    _write_po(catalogues, "fr", [polib.POEntry(msgid="Opening hand", msgstr="Main de départ")])

    with caplog.at_level(logging.WARNING, logger="sensei_top.i18n"):
        assert i18n.load_catalogues(catalogues) == {}
    assert any("'fr'" in r.getMessage() for r in caplog.records)


def test_a_translation_whose_placeholders_differ_is_english_and_warns(catalogues, caplog):
    """A ``.po`` entry the code's ``.format(...)`` could not fill is served
    as its msgid, with a warning naming it, while the rest of the
    catalogue still translates (rule 4: a bad entry costs one string, not
    the request)."""
    _write_po(catalogues, i18n.PT_BR, [
        polib.POEntry(msgid="{n} turns left", msgstr="faltam {n} turnos"),
        polib.POEntry(msgid="Lost to {deck}", msgstr="Perdeu para {baralho}"),
        polib.POEntry(msgid="Won on turn {n}", msgstr="Venceu"),
        polib.POEntry(msgid="Kept {cards}", msgstr="Manteve {cards} em {turn}"),
        polib.POEntry(msgid="Drew {card}", msgstr="Comprou {}"),
        polib.POEntry(msgid="Cast {card}", msgstr="Conjurou {card"),
        polib.POEntry(
            msgid="{n} mulligan", msgid_plural="{n} mulligans",
            msgstr_plural={0: "um mulligan", 1: "{n} mulligans"},
        ),
        polib.POEntry(
            msgid="{n} land", msgid_plural="{n} lands",
            msgstr_plural={0: "{n} terreno", 1: "{n} terrenos de {cor}"},
        ),
    ])
    with caplog.at_level(logging.WARNING, logger="sensei_top.i18n"):
        i18n.load_catalogues(catalogues)

    with i18n.use_language("pt-BR"):
        assert i18n._("{n} turns left") == "faltam {n} turnos"
        # A plural form may drop the count ("um"), never add a name.
        assert i18n.ngettext("{n} mulligan", "{n} mulligans", 1) == "um mulligan"
        for msgid in ("Lost to {deck}", "Won on turn {n}", "Kept {cards}", "Drew {card}",
                      "Cast {card}"):
            assert i18n._(msgid) == msgid
        assert i18n.ngettext("{n} land", "{n} lands", 1) == "{n} land"
        assert i18n.ngettext("{n} land", "{n} lands", 2) == "{n} lands"
    warned = " ".join(r.getMessage() for r in caplog.records)
    for msgid in ("Lost to {deck}", "Won on turn {n}", "Kept {cards}", "Drew {card}",
                  "Cast {card}", "{n} land"):
        assert repr(msgid) in warned
    assert repr("{n} turns left") not in warned
    assert repr("{n} mulligan") not in warned


def test_every_shipped_translation_uses_its_msgids_placeholders():
    """A translation whose placeholders differ from its msgid's fails here,
    before it reaches a user as an English string and a warning."""
    po_path = POT.parent / i18n.PT_BR / "LC_MESSAGES" / "sensei_top.po"
    assert po_path.is_file()
    problems = i18n.catalogue_problems(polib.pofile(str(po_path)))
    assert [f"{entry.msgid!r}: {reason}" for entry, reason in problems] == []


def test_the_shipped_catalogues_are_exactly_pt_br():
    """The translations that ship: Brazilian Portuguese, and nothing else
    yet. A new language adds its ``.po`` and its name here."""
    assert set(i18n.load_catalogues()) == {i18n.PT_BR}


# --- numbers and lists -----------------------------------------------------

# A spread for the byte-identical checks: zero and negative zero, rounding
# ties (exact in binary, 0.125, and not, 2.675), values that round to zero
# from below, thousands, a large and a tiny magnitude, and plain ints.
NUMBERS = [
    0.0, -0.0, 0.5, -0.5, 0.125, 0.375, 2.675, 1.005, -1.234, -0.004, 0.004,
    999.995, 1000.0, -1000.0, 1234567.891, 1e16, 1e-7, 3, -7, 0.45, 1.5, 2.5,
]
INTEGERS = [0, 7, -7, 999, 1000, -1000, 1234, 1234567, -1234567, 10**12]
# The PT-BR joining words, as the pt_BR catalogue gives them.
PT_BR_JOINS = [
    polib.POEntry(msgid="{first} and {second}", msgstr="{first} e {second}"),
    polib.POEntry(msgid="{head}, {item}", msgstr="{head}, {item}"),
    polib.POEntry(msgid="{head} and {last}", msgstr="{head} e {last}"),
]


@pytest.fixture
def pt_br_catalogue(catalogues):
    _write_po(catalogues, i18n.PT_BR, PT_BR_JOINS)
    assert set(i18n.load_catalogues(catalogues)) == {i18n.PT_BR}
    return catalogues


def _assert_english_numbers() -> None:
    for x in NUMBERS:
        for places in (0, 1, 2, 3):
            assert i18n.decimal(x, places) == f"{x:.{places}f}", (x, places)
            assert i18n.decimal(x, places, signed=True) == f"{x:+.{places}f}", (x, places)
            assert i18n.percent(x, places) == f"{x:.{places}%}", (x, places)
        assert i18n.percent(x) == f"{x:.0%}", x
        assert i18n.decimal(x, 0, grouped=True) == f"{x:,.0f}", x
        assert i18n.decimal(x) == f"{x:g}", x
    for n in INTEGERS:
        assert i18n.integer(n) == f"{n:,}", n


def test_numbers_in_english_are_todays_f_strings(pt_br_catalogue):
    """D-b: English is byte-identical to the f-string specs the backend
    writes today, by default and under ``english()`` inside a PT-BR
    request, with a PT-BR catalogue loaded."""
    _assert_english_numbers()
    with i18n.use_language("pt-BR"), i18n.english():
        _assert_english_numbers()


def test_numbers_in_portuguese_swap_the_separators(pt_br_catalogue):
    """Decimal comma and ``.`` thousands, percent with no space, as
    ``Intl.NumberFormat('pt-BR')`` writes them for the dashboard
    (``web/src/lib/format.ts``). Ungrouped where English is ungrouped,
    like ``formatFixed``."""
    with i18n.use_language("pt-BR"):
        assert i18n.decimal(0.5, 2) == "0,50"
        assert i18n.decimal(-1234.5, 2) == "-1234,50"
        assert i18n.decimal(0.12, 2, signed=True) == "+0,12"
        assert i18n.decimal(-0.3, 2, signed=True) == "-0,30"
        assert i18n.decimal(3.25, 1) == "3,2"  # Python's rounding, in either language
        assert i18n.decimal(1000.0, 0, grouped=True) == "1.000"
        assert i18n.decimal(1234567.0, 0, grouped=True) == "1.234.567"
        assert i18n.decimal(2.5) == "2,5"
        assert i18n.decimal(5) == "5"
        assert i18n.percent(0.45) == "45%"
        assert i18n.percent(0.125, 1) == "12,5%"
        assert i18n.percent(-0.05) == "-5%"
        assert i18n.integer(999) == "999"
        assert i18n.integer(1234) == "1.234"
        assert i18n.integer(-1000) == "-1.000"
        assert i18n.integer(1234567) == "1.234.567"


def test_numbers_follow_the_language_the_text_resolves_to(no_catalogues):
    """With no PT-BR catalogue a PT-BR request reads English, words and
    numbers alike (``format.ts``'s ``resolvedLanguage`` rule), so 2a's
    byte-identical-without-a-catalogue check keeps holding."""
    with i18n.use_language("pt-BR"):
        _assert_english_numbers()
        assert i18n.join(["a", "b", "c"]) == "a, b and c"


@pytest.mark.parametrize(("items", "english", "portuguese"), [
    ([], "", ""),
    (["a"], "a", "a"),
    (["a", "b"], "a and b", "a e b"),
    (["a", "b", "c"], "a, b and c", "a, b e c"),
    (["a", "b", "c", "d"], "a, b, c and d", "a, b, c e d"),
])
def test_join(pt_br_catalogue, items, english, portuguese):
    """D-d: no comma before the last word, in either language."""
    assert i18n.join(items) == english
    assert i18n.join(iter(items)) == english
    with i18n.use_language("pt-BR"):
        assert i18n.join(items) == portuguese
        with i18n.english():
            assert i18n.join(items) == english


def test_n_marks_without_translating(marker_catalogue):
    with i18n.use_language("pt-BR"):
        assert i18n.N_(PROBE) == PROBE
        assert i18n._(i18n.N_(PROBE)) == MARKER + PROBE


def test_tier_and_swing_words_translate_and_keep_their_english(marker_catalogue):
    """``TIER_WORDS`` keeps its English for prompts and tests (D-a);
    ``tier_words`` and ``swing_words`` read the request's language."""
    english = {tier: tier_words(tier) for tier in TIERS}
    swings = [swing_words(drop) for drop in (SWING_DECISIVE, SWING_NOTABLE, 0.0)]
    assert english == TIER_WORDS
    with i18n.use_language("pt-BR"):
        assert {tier: tier_words(tier) for tier in TIERS} == {
            tier: MARKER + words for tier, words in TIER_WORDS.items()
        }
        assert english == TIER_WORDS, "the constant stays English for prompts"
        assert [swing_words(drop) for drop in (SWING_DECISIVE, SWING_NOTABLE, 0.0)] == [
            MARKER + words for words in swings
        ]
        with i18n.english():
            assert {tier: tier_words(tier) for tier in TIERS} == english
    assert len(set(swings)) == 3


# --- the template ----------------------------------------------------------


@pytest.mark.skipif(
    importlib.util.find_spec("sensei_top.ai") is None,
    reason="the .pot is extracted from the whole tree, which every build ships with ai/",
)
def test_the_pot_is_current():
    """Regenerate with ``uv run python scripts/i18n_extract.py``."""
    assert POT.read_text(encoding="utf-8") == extractor.render_pot()


def test_every_msgid_has_a_pt_br_translation_and_no_orphans():
    """A wrapped string with no Portuguese, or a Portuguese entry for a
    string the code no longer has, fails here. An entry counts only when it
    is translated and not fuzzy (a fuzzy entry is dropped at compile and
    serves English), every form is non-blank (a blank form is served
    blank), and a plural has exactly the indexes the ``Plural-Forms``
    header declares (a missing index serves English for that count)."""
    po_path = POT.parent / i18n.PT_BR / "LC_MESSAGES" / "sensei_top.po"
    assert po_path.is_file()
    pot = polib.pofile(str(POT))
    catalogue = polib.pofile(str(po_path))
    match = re.search(r"nplurals\s*=\s*(\d+)", catalogue.metadata.get("Plural-Forms", ""))
    assert match, "the .po has no Plural-Forms nplurals"
    nplurals = int(match.group(1))
    present = {(e.msgctxt, e.msgid): e for e in catalogue if not e.obsolete}
    problems = []
    for entry in pot:
        found = present.get((entry.msgctxt, entry.msgid))
        if found is None or not found.translated():
            problems.append(f"{entry.msgid!r}: missing, empty or fuzzy")
        elif entry.msgid_plural:
            forms = found.msgstr_plural
            if set(forms) != set(range(nplurals)) or not all(f.strip() for f in forms.values()):
                problems.append(f"{entry.msgid!r}: plural forms are not {nplurals} non-blank ones")
        elif not found.msgstr.strip():
            problems.append(f"{entry.msgid!r}: blank")
    in_pot = {(e.msgctxt, e.msgid) for e in pot}
    orphans = [repr(msgid) for ctxt, msgid in present if (ctxt, msgid) not in in_pot]
    assert problems == []
    assert orphans == []


def _source_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "src" / "sensei_top"
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_the_extractor_collects_sorted_msgids_without_line_numbers(tmp_path):
    root = _source_tree(tmp_path, {
        "b.py": (
            "from sensei_top.i18n import _, ngettext\n"
            "def f(n):\n"
            "    return _('Zebra'), ngettext('{n} game', '{n} games', n)\n"
        ),
        "sub/a.py": (
            "from sensei_top import i18n\n"
            "x = 1\n"
            "def g():\n"
            "    return i18n._('Apple {name}').format(name='x'), i18n._('Zebra')\n"
        ),
        "c.py": "def h(_):\n    return [_ for _ in range(3)]\n",
    })
    pot = polib.pofile(extractor.render_pot(root))

    assert [e.msgid for e in pot] == ["Apple {name}", "Zebra", "{n} game"]
    by_id = {e.msgid: e for e in pot}
    assert by_id["Zebra"].occurrences == [("sensei_top/b.py", ""), ("sensei_top/sub/a.py", "")]
    assert by_id["{n} game"].msgid_plural == "{n} games"
    assert "python-brace-format" in by_id["Apple {name}"].flags
    assert "python-brace-format" not in by_id["Zebra"].flags
    assert "#: sensei_top/b.py sensei_top/sub/a.py\n" in extractor.render_pot(root)


@pytest.mark.parametrize(("source", "reason"), [
    ("_(name)", "string literals"),
    ("_(f'{x} games')", "string literals"),
    ("_('a' + 'b')", "string literals"),
    ("_('{} games')", "positional"),
    ("_('{0} games')", "positional"),
    ("ngettext('{n} game', '{} games', n)", "positional"),
    ("_('{unclosed')", "{unclosed"),
    ("_('')", "header"),
    ("_('a', 'b')", "positional argument"),
    ("ngettext('a', 'b')", "positional argument"),
])
def test_the_extractor_refuses_a_call_it_cannot_extract(tmp_path, source, reason):
    root = _source_tree(tmp_path, {"m.py": f"def f(name, x, n):\n    return {source}\n"})
    with pytest.raises(extractor.ExtractError) as excinfo:
        extractor.render_pot(root)
    assert excinfo.value.problems[0].startswith("sensei_top/m.py:2: ")
    assert reason in excinfo.value.problems[0]


def test_the_extractor_refuses_one_msgid_with_two_plurals(tmp_path):
    root = _source_tree(tmp_path, {"m.py": (
        "def f():\n"
        "    return ngettext('{n} game', '{n} games', 1), _('{n} game')\n"
    )})
    with pytest.raises(extractor.ExtractError) as excinfo:
        extractor.render_pot(root)
    assert excinfo.value.problems == [
        "sensei_top/m.py:2: '{n} game' already has plural '{n} games', not None"
    ]


IMPORT_TIME = "runs at import time"
REBOUND = "is not the translation function"


@pytest.mark.parametrize(("source", "line", "reason"), [
    ("X = _('Opening hand')\n", 1, IMPORT_TIME),
    ("class C:\n    X = i18n._('Opening hand')\n", 2, IMPORT_TIME),
    ("def f(text=_('Opening hand')):\n    return text\n", 1, IMPORT_TIME),
    ("@decorate(_('Opening hand'))\ndef f():\n    pass\n", 1, IMPORT_TIME),
    ("def f(items):\n    for _ in items:\n        pass\n    return _('Opening hand')\n",
     4, REBOUND),
    ("def f(pairs):\n    a, _ = pairs\n    return _('Opening hand')\n", 3, REBOUND),
    ("def f():\n    _ = 1\n    return _('Opening hand')\n", 3, REBOUND),
    ("def f(rows):\n    keys = [k for k, _ in rows]\n    return _('Opening hand'), keys\n",
     3, REBOUND),
    ("def f(_):\n    return _('Opening hand')\n", 2, REBOUND),
    ("def f():\n    try:\n        pass\n    except ValueError as _:\n        pass\n"
     "    return _('Opening hand')\n", 6, REBOUND),
    ("def f():\n    _ = 1\n    def g():\n        return _('Opening hand')\n    return g\n",
     4, REBOUND),
    ("def f(n, items):\n    for ngettext in items:\n        pass\n"
     "    return ngettext('{n} game', '{n} games', n)\n", 4, REBOUND),
])
def test_the_extractor_refuses_import_time_and_shadowed_calls(tmp_path, source, line, reason):
    """Trap 2 of ``i18n.py``: text made at import time is English forever.
    And the throwaway-``_`` idiom turns ``_()`` into a call on whatever
    the loop left behind — a crash, or worse, no crash."""
    root = _source_tree(tmp_path, {"m.py": (
        "from sensei_top import i18n\nfrom sensei_top.i18n import _, ngettext\n" + source
    )})
    with pytest.raises(extractor.ExtractError) as excinfo:
        extractor.render_pot(root)
    [problem] = excinfo.value.problems
    assert problem.startswith(f"sensei_top/m.py:{line + 2}: ")
    assert reason in problem


def test_the_extractor_accepts_calls_that_run_inside_a_function(tmp_path):
    """The other side of the same rules: a method, a lambda's body, a
    function's own import of ``_``, and ``i18n._`` beside a local ``_``
    are all calls at request time on the real function."""
    root = _source_tree(tmp_path, {"m.py": (
        "from sensei_top import i18n\n"
        "from sensei_top.i18n import _\n"
        "class C:\n"
        "    def label(self):\n"
        "        return _('Method')\n"
        "LATER = lambda: _('Lambda')\n"
        "def f(pairs):\n"
        "    from sensei_top.i18n import _\n"
        "    return _('Imported')\n"
        "def g(pairs):\n"
        "    a, _ = pairs\n"
        "    return i18n._('Attribute')\n"
    )})
    assert [e.msgid for e in polib.pofile(extractor.render_pot(root))] == [
        "Attribute", "Imported", "Lambda", "Method",
    ]


def test_the_extractor_collects_n_constants_and_their_translation(tmp_path):
    """D-a: ``N_()`` may run at import time, in a module constant, a dict
    of them or a class body, and its msgid lands in the template like
    ``_()``'s; ``_(CONSTANT)`` and ``_(WORDS[key])`` then translate a
    constant the same module binds to them."""
    root = _source_tree(tmp_path, {"m.py": (
        "from sensei_top import i18n\n"
        "from sensei_top.i18n import N_, _\n"
        "CAVEAT = N_('Caveat {n}')\n"
        "WORDS: dict = {'a': N_('Alpha'), 'b': i18n.N_('Beta')}\n"
        "PAIR = (N_('Left'), N_('Right'))\n"
        "class C:\n"
        "    LABEL = N_('Class label')\n"
        "def f(key, n):\n"
        "    return _(CAVEAT).format(n=n), _(WORDS[key]), i18n._(PAIR[0]), _('Caveat {n}')\n"
    )})
    pot = polib.pofile(extractor.render_pot(root))
    assert [e.msgid for e in pot] == ["Alpha", "Beta", "Caveat {n}", "Class label", "Left", "Right"]
    by_id = {e.msgid: e for e in pot}
    assert by_id["Caveat {n}"].occurrences == [("sensei_top/m.py", "")]
    assert "python-brace-format" in by_id["Caveat {n}"].flags


@pytest.mark.parametrize(("source", "line", "reason"), [
    # Still refused at import time: _() of a constant, not just of a literal.
    ("X = N_('Opening hand')\nY = _(X)\n", 2, IMPORT_TIME),
    # Not an N_() constant: a plain string, a mixed dict, a second binding,
    # a name the function rebinds, a global assignment, a method call.
    ("X = 'Opening hand'\ndef f():\n    return _(X)\n", 3, "string literals"),
    ("W = {'a': N_('A'), 'b': 'B'}\ndef f(k):\n    return _(W[k])\n", 3, "string literals"),
    ("X = N_('A')\nX = 'B'\ndef f():\n    return _(X)\n", 4, "string literals"),
    ("X = N_('A')\ndef f(X):\n    return _(X)\n", 3, "string literals"),
    ("X = N_('A')\ndef g():\n    global X\n    X = 'B'\ndef f():\n    return _(X)\n",
     6, "string literals"),
    ("W = {'a': N_('A')}\ndef f(k):\n    return _(W.get(k))\n", 3, "string literals"),
    # Changed in place through a subscript, at module level or in a function.
    ("W = {'a': N_('A')}\nW['b'] = 'B'\ndef f(k):\n    return _(W[k])\n",
     4, "string literals"),
    ("W = {'a': N_('A')}\ndef g():\n    W['a'] += '!'\ndef f(k):\n    return _(W[k])\n",
     5, "string literals"),
    ("def f(name):\n    return N_(name)\n", 2, "string literals"),
    ("def f(pairs):\n    a, N_ = pairs\n    return N_('Opening hand')\n", 3, REBOUND),
])
def test_the_extractor_refuses_what_n_does_not_cover(tmp_path, source, line, reason):
    root = _source_tree(tmp_path, {"m.py": (
        "from sensei_top import i18n\nfrom sensei_top.i18n import N_, _\n" + source
    )})
    with pytest.raises(extractor.ExtractError) as excinfo:
        extractor.render_pot(root)
    [problem] = excinfo.value.problems
    assert problem.startswith(f"sensei_top/m.py:{line + 2}: ")
    assert reason in problem


def test_only_i18n_py_may_define_the_functions_it_calls(tmp_path):
    """``i18n.py`` defines ``_`` and calls it (``join``); anywhere else a
    module-level ``def _`` is a rebinding like any other."""
    source = (
        "def _(message):\n    return message\n"
        "def join():\n    return _('{first} and {second}')\n"
    )
    root = _source_tree(tmp_path, {"i18n.py": source})
    assert [e.msgid for e in polib.pofile(extractor.render_pot(root))] == ["{first} and {second}"]

    other = _source_tree(tmp_path / "other", {"helpers.py": source})
    with pytest.raises(extractor.ExtractError) as excinfo:
        extractor.render_pot(other)
    [problem] = excinfo.value.problems
    assert problem.startswith("sensei_top/helpers.py:4: ")
    assert REBOUND in problem


# --- the request's language ------------------------------------------------


def test_the_language_middleware_runs_inside_the_guard():
    """The guard must stay outermost: ``user_middleware`` lists the
    outermost first."""
    app = create_app("unused.db")
    assert [m.cls for m in app.user_middleware] == [LoopbackGuard, RequestLanguage]


def test_each_request_is_translated_into_its_own_language(marker_catalogue, make_client):
    """Sync routes run on the threadpool, async ones on the event loop;
    both must see the request's language, and it must not outlive the
    request."""
    app = FastAPI()
    app.add_middleware(RequestLanguage)

    @app.get("/sync")
    def sync_route() -> dict:
        return {"language": i18n.current_language(), "text": i18n._(PROBE)}

    @app.get("/async")
    async def async_route() -> dict:
        return {"language": i18n.current_language(), "text": i18n._(PROBE)}

    with make_client(app) as client:
        for path in ("/sync", "/async"):
            assert client.get(path, headers={"Accept-Language": "pt-BR"}).json() == {
                "language": i18n.PT_BR, "text": MARKER + PROBE,
            }
            for header in ({}, {"Accept-Language": "en-US,en;q=0.9"}):
                assert client.get(path, headers=header).json() == {
                    "language": i18n.ENGLISH, "text": PROBE,
                }
    assert i18n.current_language() == i18n.ENGLISH


# --- the API, with and without Accept-Language ---------------------------


@pytest.fixture
def fixture_db(tmp_path):
    db_path = tmp_path / "api.db"
    conn = open_database(db_path)
    ingest_file(conn, FIXTURE, locale_hint="mdy")
    project(conn)
    conn.close()
    return db_path


@pytest.fixture
def client(fixture_db, make_client):
    with make_client(create_app(fixture_db)) as c:
        yield c


# Routes the sweep leaves out, and why.
SWEEP_SKIPS = {
    # A cache miss downloads the image from Scryfall; tests make no network calls.
    "/api/cards/{grp_id}/image",
    "/api/cards/{grp_id}/art",
}


def _get_paths(client, key: str) -> list[str]:
    values = {
        "match_id": MATCH_WIN, "key": key, "archetype_key": "no-such-archetype",
        "report_id": "1",
    }
    schema = client.app.openapi()["paths"]
    return [
        path.format(**values)
        for path, operations in schema.items()
        if "get" in operations and path.startswith("/api/") and path not in SWEEP_SKIPS
    ]


def test_every_get_route_answers_byte_identically_without_a_catalogue(no_catalogues, client):
    """With no PT-BR catalogue, asking for PT-BR
    changes nothing — not a byte, not a status."""
    key = client.get("/api/guide/decks").json()[0]["key"]
    paths = _get_paths(client, key)
    assert f"/api/matches/{MATCH_WIN}/report" in paths

    for path in paths:
        english = client.get(path)
        portuguese = client.get(path, headers={"Accept-Language": "pt-BR"})
        assert (portuguese.status_code, portuguese.content) == (
            english.status_code, english.content,
        ), path


def test_the_list_diffs_duplicate_warnings_are_written_in_the_request_language(
    marker_catalogue,
):
    """``_list_diff_out`` writes each warning from ``ListDiff.duplicates``,
    so a diff built in English (the RCQ preview's, for its prompt) still
    reaches a Portuguese page in Portuguese. Both the sentence and the
    ``join`` of the names are msgids, so the marker shows twice."""
    diff = ListDiff(
        archetype_key="k", archetype_name="Arch", winning_decks=5, min_wins=3,
        maindeck=(), sideboard=(), duplicate_warnings=(),
        duplicates=(DuplicateNames(names=("Card A", "Card B"), shares=(0.5, 0.25)),),
    )
    english = (
        "Card A and Card B share an identical type line and mana cost and never co-occur "
        "in one decklist — they may be the same card under two names: Card A (50%), "
        "Card B (25%)."
    )
    assert _list_diff_out(diff).duplicate_warnings == [english]
    with i18n.use_language("pt-BR"):
        portuguese = _list_diff_out(diff).duplicate_warnings
    assert portuguese == [MARKER + english.replace("Card A and", MARKER + "Card A and", 1)]


def test_top8_names_translate_only_the_unclassified_sentinel(marker_catalogue):
    """``RecentEvent.top8`` holds archetype names, never translated, beside
    the ``UNCLASSIFIED`` sentinel, which is."""
    assert guide_rcq.top8_name(guide_rcq.UNCLASSIFIED) == "(unclassified)"
    with i18n.use_language("pt-BR"):
        assert guide_rcq.top8_name(guide_rcq.UNCLASSIFIED) == MARKER + "(unclassified)"
        assert guide_rcq.top8_name("Mardu Discard") == "Mardu Discard"


# --- the coach evidence and the routes' details ----------------------------


def test_a_404_detail_is_written_in_the_request_language(marker_catalogue, client):
    response = client.get("/api/matches/no-such-match/opponent-deck/candidates",
                          headers={"Accept-Language": "pt-BR"})
    assert response.status_code == 404
    assert response.json()["detail"] == MARKER + "No match no-such-match."
    assert client.get(
        "/api/matches/no-such-match/opponent-deck/candidates"
    ).json()["detail"] == "No match no-such-match."
