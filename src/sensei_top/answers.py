"""The answer contract: what every copied prompt asks an assistant to send
back, and the one reader of what comes back.

A copied prompt leaves the app and its answer comes back by hand — pasted
into a card, or saved to a file for ``guide``, ``brief`` or ``rcq
--import``. Nothing ties the two together except the text itself, so the
prompt asks for one JSON object whose first fields say which card it is for
and which data it was written for, and the answer itself under ``"answer"``:

    {"for": "guide:KEY", "context": "<hash>", "answer": {...}}

``answer_format`` writes that instruction (English, like every prompt,
``docs/i18n.md``); ``read_answer`` reads it back. Every card's ``for`` is
built by one of the ``*_for`` functions below, so a prompt and the code that
stores its answer can never spell it differently. How the dashboard's
paste box and the CLI imports use it: docs/llm.md, "Saving a pasted answer".

Traps this module exists to avoid:

1. **The header is untrusted input, like the body.** ``for`` is only ever
   compared with the card's own; it is never echoed into SQL, a path or a
   message (``AnswerError.belongs_to`` carries the *kind* it names, and only
   a kind this module knows). ``context`` is stored — it is what lets the
   card's existing staleness say an answer was written for older data —
   so it must first have the shape of the hash it stands for
   (``CONTEXT_SHAPE``); anything else means it was edited.
2. **The header nests the body rather than sitting beside it.** No body
   schema has a ``for`` or ``context`` field today; nesting means none can
   collide later, and an answer with no ``"for"`` at all is told apart
   cleanly: the whole object is the body. That is the shape of every answer
   saved before this contract, which the CLI imports still accept with a
   warning (``require_header=False``); the dashboard requires the header.
3. **An assistant wraps JSON.** A ```` ```json ```` fence, or a sentence
   before or after the object, is the ordinary case, not a malformed
   answer. ``_extract_object`` unwraps both before giving up.
4. **The sentences are the API's prose**, keyed with ``_()`` in the
   request's language; ``{card}`` and ``{subject}`` are each their own
   msgid, the determiner inside, so a translation can agree in gender.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sensei_top.i18n import N_, _

__all__ = [
    "CONTEXT_SHAPE",
    "LEAKS_FOR",
    "MAX_ANSWER_BYTES",
    "PASTED_AUTHOR",
    "PROSE",
    "Answer",
    "AnswerError",
    "answer_format",
    "brief_for",
    "check_length",
    "coach_for",
    "coverage_for",
    "guide_for",
    "headerless_warning",
    "match_for",
    "prose_of",
    "prose_schema",
    "rcq_for",
    "read_answer",
    "unreadable",
]

# Every staleness hash an answer can carry is a SHA-256 hex digest:
# brief/store.py::list_hash (the deck guide, briefs, coverage) and
# review/narrative_store.py's context hash (the prose cards).
CONTEXT_SHAPE = re.compile(r"[0-9a-f]{64}")

# A body past this is 413: no card's answer comes near it.
MAX_ANSWER_BYTES = 256 * 1024

# Who a pasted-in answer says wrote it: stored where a model id would be;
# the dashboard shows it as keyed text, never as this word.
PASTED_AUTHOR = "pasted"

LEAKS_FOR = "leaks"

# The one field a prose card's answer carries (match report, leaks, coach).
PROSE = "prose"

_CARD_NAMES = {
    "guide": N_("a deck guide"),
    "brief": N_("a matchup brief"),
    "coverage": N_("a matchup coverage"),
    "rcq": N_("an RCQ guide"),
    "match": N_("a match report"),
    "leaks": N_("the training plan"),
    "coach": N_("a coach report"),
}

# The same kind of card, another key. The leak plan has no key, so no entry.
_SUBJECTS = {
    "guide": N_("another deck"),
    "coverage": N_("another deck"),
    "rcq": N_("another deck"),
    "brief": N_("another deck or opponent"),
    "match": N_("another match"),
    "coach": N_("another format"),
}

# The one card whose prompt carries no context: an RCQ guide records one
# pasted list and has no staleness hash. Every other card's answer must
# bring its context back, since it is stored as the hash the answer was
# written for and a missing one would have to be guessed (rule 4).
_NO_CONTEXT = frozenset({"rcq"})

_FENCE = re.compile(r"```[A-Za-z]*[ \t]*\r?\n(.*?)```", re.DOTALL)


def guide_for(key: str) -> str:
    return f"guide:{key}"


def brief_for(key: str, archetype_key: str) -> str:
    return f"brief:{key}:{archetype_key}"


def coverage_for(key: str) -> str:
    return f"coverage:{key}"


def rcq_for(key: str) -> str:
    return f"rcq:{key}"


def match_for(match_id: str) -> str:
    return f"match:{match_id}"


def coach_for(fmt: str) -> str:
    return f"coach:{fmt}"


@dataclass(frozen=True, slots=True)
class Answer:
    """What ``read_answer`` hands back: the card's own answer, the hash it
    was written for (``None`` for an RCQ guide, which has none, and for a
    headerless answer), and whether it
    had no header at all (an answer saved before this contract)."""

    body: dict
    context: str | None
    headerless: bool = False


class AnswerError(ValueError):
    """An answer that cannot be stored, with a sentence in the request's
    language. ``belongs_to`` is the kind of card the answer says it is for
    (``"guide"``, ``"match"``, …) when that is why it was refused; ``status``
    is the HTTP status a route answers with."""

    def __init__(
        self, message: str, *, belongs_to: str | None = None, status: int = 422,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.belongs_to = belongs_to
        self.status = status


def prose_schema(description: str) -> dict:
    """The body schema of a prose card: one string, described by the card's
    own instruction for what the prose is."""
    return {
        "type": "object",
        "properties": {PROSE: {"type": "string", "description": description}},
        "required": [PROSE],
    }


def _is_prose(body_schema: dict) -> bool:
    return set(body_schema.get("properties") or {}) == {PROSE}


def answer_format(for_: str, context: str | None, body_schema: dict) -> str:
    """The instruction every copied prompt ends with: one JSON object, the
    header copied back verbatim, then the body ``body_schema`` describes.
    ``context`` is the hash the card's staleness compares; a card with none
    passes ``None`` and the prompt asks for ``for`` alone."""
    if context is not None:
        lead = (
            "Answer with exactly one JSON object and nothing else: no text before or\n"
            "after it. The tracker this prompt came from reads the answer back, and its\n"
            "first two fields tell it which card the answer belongs to and which data it\n"
            "was written for, so copy them exactly as they are written here:\n"
        )
        header = [
            f'  "for": {json.dumps(for_, ensure_ascii=False)},',
            f'  "context": {json.dumps(context, ensure_ascii=False)},',
        ]
    else:
        lead = (
            "Answer with exactly one JSON object and nothing else: no text before or\n"
            "after it. The tracker this prompt came from reads the answer back, and its\n"
            "first field tells it which card the answer belongs to, so copy it exactly\n"
            "as it is written here:\n"
        )
        header = [f'  "for": {json.dumps(for_, ensure_ascii=False)},']
    parts = [
        lead,
        "{",
        *header,
        '  "answer": {an object matching the schema below}',
        "}",
        "",
        'The schema for "answer":',
        json.dumps(body_schema, indent=2),
    ]
    text = "\n".join(parts)
    if _is_prose(body_schema):
        text += (
            '\n\nPut the whole text in "prose" as a single JSON string: write each line\n'
            'break as \\n and each quotation mark as \\".'
        )
    return text


def _loads_object(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _extract_object(raw: str) -> dict | None:
    """The JSON object in ``raw``: the whole text, else the first fenced
    block that is one, else everything from the first ``{`` to the last
    ``}``. ``None`` when none of those parses as an object."""
    text = raw.strip()
    found = _loads_object(text)
    if found is not None:
        return found
    for fenced in _FENCE.findall(text):
        found = _loads_object(fenced.strip())
        if found is not None:
            return found
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return _loads_object(text[start:end + 1])
    return None


def _no_header() -> AnswerError:
    return AnswerError(_(
        'The answer has no "for" line, so there is no telling where it belongs. '
        "Copy the prompt here again and paste the new answer."
    ))


def _kind(for_: str) -> str:
    return for_.split(":", 1)[0]


def _wrong_card(got: str, expected_for: str) -> AnswerError:
    """The refusal for an answer written for another card, naming the kind
    it is for — never the rest of its ``for``, which is untrusted text."""
    kind = _kind(got)
    if kind not in _CARD_NAMES:
        return _no_header()
    card = _(_CARD_NAMES[kind])
    if kind != _kind(expected_for):
        return AnswerError(
            _("This answer is for {card}, not this one. Paste it there.").format(card=card),
            belongs_to=kind,
        )
    if kind not in _SUBJECTS:
        return _no_header()
    return AnswerError(
        _("This answer is for {card} of {subject}. Paste it there.").format(
            card=card, subject=_(_SUBJECTS[kind]),
        ),
        belongs_to=kind,
    )


def read_answer(raw: str | dict, expected_for: str, *, require_header: bool) -> Answer:
    """Read one pasted or imported answer for the card ``expected_for``
    names. Raises ``AnswerError`` when it is not a JSON object, belongs to
    another card (checked before anything else), carries an edited or
    missing ``context`` (every card but the RCQ guide has one, and it is
    stored, never guessed), or has a header but no ``"answer"``.

    With no ``"for"`` at all the answer is refused when ``require_header``
    (the dashboard), and otherwise read whole as the body (the CLI imports,
    for answers saved before the contract): ``headerless`` says which, so
    the caller can warn (``headerless_warning``).

    The body is returned unparsed: each card's own parser
    (``guide_narrative_from_json``, ``brief_from_json``, ``rcq_from_json``,
    ``prose_of``) reads it and raises its own error, which a route reports
    through ``unreadable``."""
    obj = raw if isinstance(raw, dict) else _extract_object(raw)
    if obj is None:
        raise AnswerError(_(
            "The answer is not a JSON object. Paste the whole answer, "
            "from its first `{{` to its last `}}`."
        ).format())

    if "for" not in obj:
        if require_header:
            raise _no_header()
        return Answer(body=obj, context=None, headerless=True)

    got = obj["for"]
    if not isinstance(got, str):
        raise _no_header()
    if got != expected_for:
        raise _wrong_card(got, expected_for)

    context = obj.get("context")
    if _kind(got) in _NO_CONTEXT:
        context = None
    elif not isinstance(context, str) or CONTEXT_SHAPE.fullmatch(context) is None:
        raise AnswerError(_(
            'The answer\'s "context" line was changed. It has to be copied back '
            "exactly as the prompt gave it."
        ))

    body = obj.get("answer")
    if not isinstance(body, dict):
        raise AnswerError(_('The answer has its "for" line but no "answer" object after it.'))
    return Answer(body=body, context=context)


def unreadable(detail: str) -> AnswerError:
    """The refusal for a body its card's parser could not read; ``detail``
    is the parser's own message, in English like the CLI's."""
    return AnswerError(_("The answer could not be read: {detail}").format(detail=detail))


def check_length(raw: str) -> None:
    """Refuse (413) a pasted body longer than ``MAX_ANSWER_BYTES``."""
    if len(raw.encode("utf-8")) > MAX_ANSWER_BYTES:
        raise AnswerError(
            _(
                "The answer is longer than any answer here needs to be. "
                "Check that only the answer was pasted."
            ),
            status=413,
        )


def prose_of(answer: Answer) -> str:
    """A prose card's text, from the body ``prose_schema`` describes."""
    prose = answer.body.get(PROSE)
    if not isinstance(prose, str):
        raise unreadable(f'expected a "{PROSE}" string.')
    if not prose.strip():
        raise AnswerError(_("The answer has no text in it."))
    return prose


def headerless_warning() -> str:
    """What a CLI import says when it accepts an answer with no header."""
    return _(
        'This answer has no "for" line, so it was read as one saved before '
        "answers carried it."
    )
