"""The dashboard's prose in the reader's language — and every prompt in English.

``api/app.py``'s middleware enters ``use_language`` for each request's
``Accept-Language``; this server stores no language setting (see
docs/i18n.md, "The language, from setting to sentence"). Every user-facing
sentence the API builds goes through ``_()`` or ``ngettext()``, with the
English text as the msgid: a missing catalogue, a missing entry or an
English request all give back exactly the English the code wrote.

Catalogues are ``locale/<lang>/LC_MESSAGES/sensei_top.po``, read once at
import with ``polib`` and compiled in memory into a ``GNUTranslations``; no
``.mo`` file is ever written. For the template and its extractor, see
docs/i18n.md, "Keying a string in the API".

Traps this module exists to avoid:

1. **A translated sentence must never reach a prompt.** A ``Finding``'s
   ``title`` and ``detail`` reach the dashboard *and* the match-report and
   coach prompts. Every prompt builder enters ``english()`` (it is also a
   decorator), so anything it formats — or builds by calling the same
   analyzers the dashboard uses — comes out in English whatever the
   request asked for. ``english()`` cannot reach back in time, though: an
   object built *before* the builder ran, in the request's language,
   carries its translated text in. Build a prompt's evidence inside the
   builder's scope, never hand it an object a page has already rendered.
2. **No ``_()`` at import time.** A module-level constant is evaluated once,
   in no request's language. Make it a function, or mark it with ``N_()``
   (gettext's own convention: a no-op the extractor collects) and
   translate it where it is used, ``_(CONSTANT)`` or ``_(WORDS[key])``.
3. **Named placeholders only**: ``_("{n} of {total} games").format(...)``,
   never ``%s`` or ``{}`` — a translation may need to reorder them, and the
   extractor refuses a positional one.
4. **The language is a ``ContextVar``, not a global.** Requests run
   concurrently on the threadpool; a ``ContextVar`` set by the middleware
   is copied into the worker thread that runs the route, and reset when
   the request ends, so one request's language never leaks into another's.
5. **A broken catalogue is English, never a crash** (AGENTS.md rule 4): a
   ``.po`` that does not parse, or a language this module does not
   negotiate, logs a warning and is skipped. So is one *entry* whose
   placeholders differ from its msgid's (``catalogue_problems``): its
   ``.format(...)`` would raise ``KeyError`` mid-request, a 500 where
   English would have done.
6. **A number in a sentence is formatted here, not by an f-string spec.**
   ``decimal``, ``percent`` and ``integer`` write exactly what ``:.2f``,
   ``:.0%`` and ``:,`` write in English, and swap the separators in
   Portuguese (``0,50``, ``1.234``, ``45%``), as the dashboard's
   ``web/src/lib/format.ts`` does. Not the ``locale`` module: its setting
   is process-global, so one request's language would leak into another's.
"""

from __future__ import annotations

import gettext
import io
import logging
import string
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.resources import files
from importlib.resources.abc import Traversable

import polib

log = logging.getLogger(__name__)

DOMAIN = "sensei_top"
ENGLISH = "en"
PT_BR = "pt_BR"
# Languages a catalogue may exist for. English is the msgid itself, so it
# never has one.
TRANSLATED = (PT_BR,)
# Read through importlib.resources, like db.py's migrations, so an installed
# wheel and the frozen server (PyInstaller's collect_data_files) find it too.
LOCALE_DIR: Traversable = files("sensei_top") / "locale"

_language: ContextVar[str] = ContextVar("sensei_top_language", default=ENGLISH)
_catalogues: dict[str, gettext.GNUTranslations] = {}
# Languages already warned about having no catalogue — once per process, not
# once per string, or one page load would write hundreds of identical lines.
_warned_missing: set[str] = set()


def language_for(header: str | None) -> str:
    """The language an ``Accept-Language`` value asks for: ``PT_BR`` for any
    Portuguese tag (``pt-BR``, ``pt``, ``pt-PT``), ``ENGLISH`` for anything
    else, including no header and a malformed one.

    Tags are tried in the header's own preference order (``q``, highest
    first; ties keep their written order), and the first one this server
    speaks wins — so ``fr, pt;q=0.5`` is Portuguese and ``en-US, pt-BR`` is
    English. A tag with ``q=0`` is one the client refuses; a ``q`` that is
    not a number drops that tag rather than guessing its weight.
    """
    if not header:
        return ENGLISH
    ranked: list[tuple[float, int, str]] = []
    for position, part in enumerate(header.split(",")):
        tag, *params = (piece.strip() for piece in part.split(";"))
        if not tag:
            continue
        weight = 1.0
        malformed = False
        for param in params:
            name, _sep, value = param.partition("=")
            if name.strip().lower() != "q":
                continue
            try:
                weight = float(value)
            except ValueError:
                malformed = True
        if malformed or not 0 < weight <= 1:
            continue
        ranked.append((-weight, position, tag.lower()))
    for _weight, _position, tag in sorted(ranked):
        primary = tag.replace("_", "-").split("-")[0]
        if primary == "pt":
            return PT_BR
        if primary in ("en", "*"):
            return ENGLISH
    return ENGLISH


def current_language() -> str:
    """The language strings are being translated into right now."""
    return _language.get()


@contextmanager
def use_language(header: str | None) -> Iterator[str]:
    """Translate into the language ``header`` (an ``Accept-Language``
    value, or a bare tag such as ``"pt-BR"``) asks for, until the block
    ends. Yields the language chosen."""
    language = language_for(header)
    token = _language.set(language)
    try:
        yield language
    finally:
        _language.reset(token)


@contextmanager
def english() -> Iterator[None]:
    """English until the block ends, whatever the request asked for — the
    scope every prompt builder runs in (trap 1 above). Also a decorator,
    ``@english()``, which is how the builders use it: a ``contextmanager``
    is a ``ContextDecorator``, and each call gets a fresh scope."""
    token = _language.set(ENGLISH)
    try:
        yield
    finally:
        _language.reset(token)


def _catalogue() -> gettext.GNUTranslations | None:
    language = _language.get()
    if language == ENGLISH:
        return None
    catalogue = _catalogues.get(language)
    if catalogue is None and language not in _warned_missing:
        _warned_missing.add(language)
        log.warning("no %s translation catalogue is installed; serving English", language)
    return catalogue


def _(message: str) -> str:
    """``message`` in the current language; ``message`` itself when the
    language is English or the catalogue has no entry for it."""
    catalogue = _catalogue()
    return message if catalogue is None else catalogue.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """The form of a counted phrase that fits ``n``, in the current
    language. Only picks the form: the caller still ``.format()``s ``n``
    into it, since a translation may place it differently."""
    catalogue = _catalogue()
    if catalogue is None:
        return singular if n == 1 else plural
    return catalogue.ngettext(singular, plural, n)


def N_(message: str) -> str:  # noqa: N802 - gettext's own name for it
    """``message``, untouched: marks a module-level display constant for
    the extractor, which collects it like ``_()``'s argument and, unlike
    ``_()``, allows it at import time. The text is translated where it is
    used, ``_(CONSTANT)``, in that request's language (trap 2)."""
    return message


# The separators each translated language swaps for English's, as its
# ``Intl.NumberFormat`` writes them. English is the f-string itself.
_SEPARATORS = {PT_BR: str.maketrans({".": ",", ",": "."})}


def _number(english: str) -> str:
    """``english`` with the active language's separators. Formatting
    follows the language the *text* resolves to, as ``format.ts`` does: a
    language with no catalogue loaded reads as English, its numbers with
    it, so a sentence never mixes English words with Portuguese digits.

    The digits are Python's, rounding included, in every language: only
    the separators move, so a number reads the same whatever the reader's
    language. Nothing is grouped that English does not group."""
    language = _language.get()
    table = _SEPARATORS.get(language) if language in _catalogues else None
    return english if table is None else english.translate(table)


def decimal(x: float, places: int | None = None, *, signed: bool = False,
            grouped: bool = False) -> str:
    """``x`` to ``places`` decimals, ``f"{x:.2f}"`` in English, ``0,50`` in
    Portuguese. ``signed`` writes a ``+`` on a positive number
    (``:+.2f``), ``grouped`` groups thousands (``:,.0f``). With no
    ``places``, as few digits as the number needs (``:g``): ``5``,
    ``2.5``."""
    spec = ("+" if signed else "") + ("," if grouped else "")
    spec += "g" if places is None else f".{places}f"
    return _number(format(x, spec))


def percent(x: float, places: int = 0) -> str:
    """A share ``x`` (0..1) as a percentage, ``f"{x:.0%}"`` in English:
    ``45%``, and ``12,5%`` in Portuguese at one place. No space before the
    sign, as ``Intl`` writes it for both languages."""
    return _number(format(x, f".{places}%"))


def integer(n: int) -> str:
    """A count with its thousands grouped, ``f"{n:,}"`` in English:
    ``1,234``; ``1.234`` in Portuguese."""
    return _number(format(n, ","))


def join(items: Iterable[str]) -> str:
    """``items`` as one phrase in the active language: ``a``, ``a and b``,
    ``a, b and c`` (no comma before the last ``and``, as the codebase's
    English has always written it); ``a e b``, ``a, b e c`` in Portuguese.
    The joining words are msgids with named placeholders, so a translation
    may reorder them. Empty gives ``""``."""
    words = list(items)
    if len(words) < 2:
        return "".join(words)
    if len(words) == 2:
        return _("{first} and {second}").format(first=words[0], second=words[1])
    head = words[0]
    for word in words[1:-1]:
        head = _("{head}, {item}").format(head=head, item=word)
    return _("{head} and {last}").format(head=head, last=words[-1])


def placeholders(text: str) -> frozenset[str] | None:
    """The named ``{placeholders}`` in ``text`` — ``None`` when it has a
    positional one (``{}``, ``{0}``) or braces that do not parse, either of
    which ``.format(name=...)`` cannot fill."""
    try:
        fields = list(string.Formatter().parse(text))
    except ValueError:
        return None
    names = set()
    for _literal, name, _spec, _conversion in fields:
        if name is None:
            continue
        head = name.split(".")[0].split("[")[0]
        if not head or head.isdigit():
            return None
        names.add(head)
    return frozenset(names)


def catalogue_problems(catalogue: polib.POFile) -> list[tuple[polib.POEntry, str]]:
    """Every translated entry whose placeholders the code could not fill,
    with the reason. A plain entry must use exactly its msgid's names. A
    plural form may use any of the names its msgid and msgid_plural use
    between them, and may leave some out (a singular form often spells the
    count as a word), but never add one. Malformed braces are a problem too.
    """
    problems = []
    for entry in catalogue.translated_entries():
        if entry.msgid_plural:
            expected = (placeholders(entry.msgid) or frozenset()) | (
                placeholders(entry.msgid_plural) or frozenset()
            )
            forms = list(entry.msgstr_plural.values())
        else:
            expected = placeholders(entry.msgid) or frozenset()
            forms = [entry.msgstr]
        for form in forms:
            found = placeholders(form)
            if found is None:
                problems.append((entry, f"{form!r} has a positional placeholder or a stray brace"))
            elif entry.msgid_plural and not found <= expected:
                problems.append((entry, f"{form!r} uses {sorted(found - expected)}, "
                                        f"which the code never passes"))
            elif not entry.msgid_plural and found != expected:
                problems.append((entry, f"{form!r} uses {sorted(found)}, "
                                        f"not the msgid's {sorted(expected)}"))
    return problems


def _compile(po_file: Traversable, language: str) -> gettext.GNUTranslations:
    """One ``.po`` compiled in memory: polib serializes the translated,
    non-fuzzy entries in the ``.mo`` layout ``GNUTranslations`` reads, and
    the bytes never touch the disk. An entry ``catalogue_problems`` names is
    left out, with a warning, so its msgid — English — is what is served."""
    catalogue = polib.pofile(po_file.read_text(encoding="utf-8"))
    for entry, reason in catalogue_problems(catalogue):
        log.warning(
            "the %s translation of %r is unusable (%s); serving English for it",
            language, entry.msgid, reason,
        )
        entry.msgstr = ""
        entry.msgstr_plural = {index: "" for index in entry.msgstr_plural}
    return gettext.GNUTranslations(io.BytesIO(catalogue.to_binary()))


def load_catalogues(locale_dir: Traversable = LOCALE_DIR) -> dict[str, gettext.GNUTranslations]:
    """Read every ``<lang>/LC_MESSAGES/sensei_top.po`` under ``locale_dir``
    and make them the catalogues ``_()`` reads, replacing whatever was
    loaded before. Runs once at import; tests call it again with a
    directory of their own, and once more with no argument to put the
    shipped catalogues back.
    """
    loaded: dict[str, gettext.GNUTranslations] = {}
    entries = sorted(locale_dir.iterdir(), key=lambda p: p.name) if locale_dir.is_dir() else []
    for language_dir in entries:
        po_file = language_dir / "LC_MESSAGES" / f"{DOMAIN}.po"
        if not language_dir.is_dir() or not po_file.is_file():
            continue
        if language_dir.name not in TRANSLATED:
            log.warning(
                "ignoring the translation catalogue for %r: not a language this server "
                "speaks (%s)", language_dir.name, ", ".join(TRANSLATED),
            )
            continue
        try:
            loaded[language_dir.name] = _compile(po_file, language_dir.name)
        # Anything polib or gettext raises on a malformed file (OSError for a
        # syntax error, ValueError/UnicodeDecodeError for bad bytes, others
        # from a corrupt header) means the same thing: this language is
        # English until the file is fixed, and the server keeps running.
        except Exception as exc:
            log.warning(
                "the %s translation catalogue could not be read (%s); serving English",
                language_dir.name, exc,
            )
    global _catalogues
    _catalogues = loaded
    _warned_missing.clear()
    return loaded


load_catalogues()
