"""The coach's reading list — the strategy writing a report may cite, and
the sites its web search may read.

Every entry here was checked by hand against the live page (title and
author as the page shows them) on 2026-09-18, and its ``summary`` was
written from that page's own content in this project's words — never a
quote, never recalled from memory (non-negotiable #4: an entry nobody
could verify is dropped, not guessed). Two entries were checked through
their publisher's search index rather than the rendered page, because
TCGplayer serves its articles as a script-rendered app no fetch can read;
their ``note`` says so.

``entries_for`` picks only what a report's own evidence calls for — the
full list never goes into a prompt. ``topics`` mixes ``Finding.code``s
(``review/analyzers/``, plus the leak finder's own ``mana_screwed``/
``mana_flooded``) with broad tags the evidence always carries
(``sideboarding`` for the game-1-vs-post-board split, ``tournament-prep``
for the LGS section).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CanonEntry:
    id: int
    author: str
    title: str
    url: str
    topics: frozenset[str]
    summary: str
    note: str | None = None

    @property
    def label(self) -> str:
        return f"R{self.id}"


CANON: tuple[CanonEntry, ...] = (
    CanonEntry(
        1, "Mike Flores", "Who's The Beatdown?",
        "https://articles.starcitygames.com/articles/whos-the-beatdown/",
        frozenset({"role_assignment", "beatdown_held_back", "control_never_ahead_on_cards"}),
        "In any matchup one deck is the aggressor and the other the controller, and the role "
        "follows from the pairing rather than from the deck's name. Playing the wrong role — "
        "racing when you should survive, or durdling when you should race — loses games on "
        "its own.",
    ),
    CanonEntry(
        2, "Mike Flores", "The Philosophy of Fire",
        "https://articles.starcitygames.com/articles/the-philosophy-of-fire/",
        frozenset({"race_ahead", "race_behind", "race_even"}),
        "Treats cards as units of damage: an aggressive deck converts each card into a share "
        "of the opponent's life total, so the question is how many cards it takes to finish "
        "them. Useful for counting whether a race is actually winnable.",
        note="Flores later credited the idea's origin to Adrian Sullivan.",
    ),
    CanonEntry(
        3, "Reid Duke", "Role Assignment",
        "https://magic.wizards.com/en/articles/archive/level-one/role-assignment-2015-01-05",
        frozenset({"role_assignment", "beatdown_held_back", "control_never_ahead_on_cards"}),
        "Duke's lesson built on Flores' question: work out before and during each game which "
        "side must press and which must stall, and let that decide attacks, blocks and what "
        "to spend removal on. The role can change mid-game as the board changes.",
    ),
    CanonEntry(
        4, "Reid Duke", "Damage Racing",
        "https://magic.wizards.com/en/articles/archive/level-one/damage-racing-2015-05-04",
        frozenset({"race_ahead", "race_behind", "race_even", "beatdown_held_back"}),
        "Your life total is a resource to spend, not to protect for its own sake. Avoid early "
        "chump blocks, deal damage whenever it's safe so a later race starts in your favour, "
        "and switch from defence to offence as soon as the board allows.",
    ),
    CanonEntry(
        5, "Reid Duke", "Tempo & Card Advantage: A Delicate Balance",
        "https://magic.wizards.com/en/articles/archive/level-one/"
        "tempo-card-advantage-delicate-balance-2014-11-17",
        frozenset({"card_advantage_swing", "control_never_ahead_on_cards", "counters_traded"}),
        "Early turns reward tempo — develop and seize the board — while late turns reward card "
        "advantage and patience. The same card (a counterspell, a bounce spell) is used "
        "differently depending on which stage the game is in.",
    ),
    CanonEntry(
        6, "Reid Duke", "Playing From Ahead, Playing From Behind",
        "https://magic.wizards.com/en/articles/archive/level-one/"
        "playing-ahead-playing-behind-2015-03-30",
        frozenset({"turning_point", "never_behind", "race_behind"}),
        "Behind: find your outs, play toward them, and make the game complicated so the "
        "opponent can go wrong. Ahead: think from their side, simplify, trade resources, and "
        "slow down on the turns that close the game.",
    ),
    CanonEntry(
        7, "Reid Duke", "Mulligans",
        "https://magic.wizards.com/en/articles/archive/level-one/mulligans-2015-01-26",
        frozenset({"mulligan_taken", "mulligans", "mana_screwed", "mana_flooded"}),
        "Fewer cards is a real cost, so the default is to keep hands with a workable land "
        "count. Mulligan harder in fast formats and with linear decks, less often with "
        "control, and loosen your standards as the hand gets smaller.",
    ),
    CanonEntry(
        8, "Reid Duke", "Play or Draw?",
        "https://magic.wizards.com/en/articles/archive/level-one/play-or-draw-2015-03-16",
        frozenset({"on_play_context", "play-draw"}),
        "Playing first is worth a lot of tempo and is the right default in Constructed; the "
        "extra card from drawing mostly helps with land drops. The faster the format, the "
        "stronger the case for being on the play.",
    ),
    CanonEntry(
        9, "Reid Duke", "The Sideboard",
        "https://magic.wizards.com/en/articles/archive/level-one/sideboard-2015-08-10",
        frozenset({"sideboarding"}),
        "Sideboard cards answer specific problems, add new angles of attack, or hate out "
        "popular strategies — planned as part of the whole 75, not bolted on. Don't board so "
        "much that the deck stops doing what it does, and practise the sideboarded "
        "configurations before an event.",
    ),
    CanonEntry(
        10, "Paulo Vitor Damo da Rosa", "There's More To Sideboarding Than You Think",
        "https://articles.starcitygames.com/magic-the-gathering/premium/"
        "theres-more-to-sideboarding-than-you-think/",
        frozenset({"sideboarding", "play-draw", "mulligans"}),
        "Board differently on the play (stay proactive) and on the draw (react, go longer). "
        "Board against the deck the opponent will have after sideboarding, not their game-1 "
        "list, and expect post-board games to be grindier — adjust mulligans and even land "
        "counts to match.",
    ),
    CanonEntry(
        11, "Reid Duke", "Board Sweepers",
        "https://magic.wizards.com/en/articles/archive/level-one/board-sweepers-2015-06-22",
        frozenset({"over_committed_into_sweeper"}),
        "Know which sweepers the format actually plays and who plays them. Creature decks "
        "should build and sequence to be resilient to them; unconditional sweepers are at "
        "their best in game 1, before the opponent can adjust.",
    ),
    CanonEntry(
        12, "Reid Duke", "Thoughtseize You",
        "https://articles.starcitygames.com/articles/thoughtseize-you/",
        frozenset({"still_live_staples"}),
        "How to use hand disruption well: decide in advance which of the opponent's key cards "
        "you need to take, and use what you see to exploit their weaknesses. Knowing the "
        "opponent's important cards is the prerequisite.",
    ),
    CanonEntry(
        13, "Reid Duke", "Becoming a Better Player",
        "https://magic.wizards.com/en/articles/archive/level-one/becoming-better-player-2015-09-28",
        frozenset({"review", "mana_screwed", "mana_flooded", "cards_stranded_in_a_loss"}),
        "Play fewer, more focused games; after each loss ask why, and separate a fluke from "
        "a recurring flaw in your deck or your play. Study strategy writing, learn from "
        "stronger players, and keep confidence and humility in balance.",
    ),
    CanonEntry(
        14, "Reid Duke", "Playing in a Grand Prix: Part I",
        "https://magic.wizards.com/en/articles/archive/level-one/playing-grand-prix-part-i-2015-05-18",
        frozenset({"tournament-prep", "tilt"}),
        "Set goals that don't depend on your final standing, look after sleep and food, and "
        "arrive early. At the table: communicate clearly, track life totals on paper, and "
        "shuffle your opponent's deck as routine.",
    ),
    CanonEntry(
        15, "Reid Duke", "Helpful Delusions",
        "https://articles.starcitygames.com/articles/helpful-delusions/",
        frozenset({"tilt", "review"}),
        "Mental habits that help results: play every game as winnable, keep playing around "
        "what matters, and measure yourself against your own improvement rather than other "
        "players.",
    ),
    CanonEntry(
        16, "Frank Karsten",
        "How Many Sources Do You Need to Consistently Cast Your Spells? A 2022 Update",
        "https://www.tcgplayer.com/content/article/"
        "How-Many-Sources-Do-You-Need-to-Consistently-Cast-Your-Spells-A-2022-Update/"
        "dc23a7d2-0a16-4c0b-ad36-586fcca03ad8/",
        frozenset({"mana_screwed", "cards_stranded_in_a_loss", "deckbuilding"}),
        "Probability tables for how many sources of a colour a deck needs to cast a spell on "
        "curve with high reliability. The check to run when coloured spells keep getting "
        "stranded.",
        note="Checked through TCGplayer's search index; the page is script-rendered.",
    ),
    CanonEntry(
        17, "Frank Karsten", "How Many Lands Do You Need in Your Deck? An Updated Analysis",
        "https://www.tcgplayer.com/content/article/"
        "How-Many-Lands-Do-You-Need-in-Your-Deck-An-Updated-Analysis/"
        "cd1c1a24-d439-4a8e-b369-b936edb0b38a/",
        frozenset({"mana_screwed", "mana_flooded", "deckbuilding"}),
        "A regression over tens of thousands of winning tournament decks: land count rises "
        "with average mana value and falls with cheap card draw or ramp, and a land/spell "
        "double-faced card counts as part of a land.",
        note="Checked through TCGplayer's search index; the page is script-rendered.",
    ),
    CanonEntry(
        18, "Richard Garfield", "Luck in Games (talk at ITU Copenhagen)",
        "https://www.youtube.com/watch?v=av5Hf7uOu-o",
        frozenset({"variance", "review"}),
        "Magic's designer on how luck and skill coexist: luck is what keeps outcomes "
        "uncertain in the short run, and skill only shows through over many games. The "
        "reason a handful of results is never a verdict.",
        note="A video, not an article.",
    ),
)

# Always offered, whatever the evidence says: role, review method, variance.
CORE_IDS: tuple[int, ...] = (1, 13, 18)

# The topics that are not a ``Finding.code``: the leak finder's two
# synthetic codes, and the broad tags ``coach/narrative.py`` derives from
# which evidence sections a report actually has.
LEAK_CODES = frozenset({"mana_screwed", "mana_flooded"})
BROAD_TAGS = frozenset({
    "sideboarding", "mulligans", "play-draw", "deckbuilding",
    "review", "variance", "tilt", "tournament-prep",
})

# The web search tool's allowlist (``llm.client.write_report``). Checked
# 2026-09-18 for live Standard metagame or strategy content. Deliberately
# absent: starcitygames.com (no current Standard coverage), channelfireball.com
# (redirects to tcgplayer.com), cardkingdom.com (no Standard content), melee.gg
# (results data, no prose). magic.wizards.com publishes no strategy any more
# but is the source of record for banned-and-restricted announcements.
ALLOWED_DOMAINS: tuple[str, ...] = (
    "magic.wizards.com",
    "tcgplayer.com",
    "mtggoldfish.com",
    "mtgazone.com",
    "hareruyamtg.com",
    "untapped.gg",
    "mtgdecks.net",
    "mtgtop8.com",
    "aetherhub.com",
)


def entries_for(
    codes: set[str] | frozenset[str], tags: set[str] | frozenset[str]
) -> list[CanonEntry]:
    """The entries a report's own evidence calls for — any whose ``topics``
    meet ``codes | tags`` — plus ``CORE_IDS``, in ``id`` order."""
    wanted = set(codes) | set(tags)
    return [e for e in CANON if e.id in CORE_IDS or e.topics & wanted]
