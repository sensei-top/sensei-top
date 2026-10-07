-- 004_archetypes.sql — the opponent's deck: downloaded archetype definitions,
-- the classifier's verdict, the user's manual corrections, and the matchup
-- metric built on top of them.
--
-- Arena never sends the opponent's decklist or deck name. Verified against a
-- real capture: every opponent draw is a zone transfer with grp_id NULL,
-- because the client omits the game object for a card we may not see, and
-- every DeckId in the log belongs to our own account. What we do get is each
-- card that became visible, and that is what these tables reason over.

-- ---------------------------------------------------------------------------
-- Reference data, exactly like `cards`: downloaded, not derived, and therefore
-- deliberately outside the projector's DELETE set so a rebuild never discards
-- a fetch.
--
-- `source` is the definition's file stem and it is the identity, because the
-- upstream `name` is not unique: Standard ships four archetype files all named
-- Midrange, and two of the fallbacks are both named Midrange as well.
-- ---------------------------------------------------------------------------
CREATE TABLE archetypes (
    format         TEXT NOT NULL,
    kind           TEXT NOT NULL CHECK (kind IN ('archetype', 'fallback')),
    source         TEXT NOT NULL,
    name           TEXT NOT NULL,
    include_color  INTEGER NOT NULL DEFAULT 1,
    definition     TEXT NOT NULL,
    fetched_at     TEXT NOT NULL,
    PRIMARY KEY (format, kind, source)
);

-- One row, so `serve` can decide whether the cache is stale without counting
-- rows, and an offline run can say how old the copy it is using is.
CREATE TABLE archetype_fetch (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    url         TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    files       INTEGER NOT NULL,
    skipped     INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- The classifier's output. Derived, so the projector deletes it along with
-- everything else: its rows point at matches a rebuild recreates.
--
-- Between project() committing and classify_matches() committing this table is
-- empty. That is a legible degraded state, not a bug: v_match_opponent falls
-- through to the colours and signature-card label for that instant rather than
-- showing a blank.
-- ---------------------------------------------------------------------------
CREATE TABLE opponent_archetype (
    match_id            TEXT PRIMARY KEY REFERENCES matches (match_id),
    format              TEXT,
    archetype_key       TEXT,
    archetype_name      TEXT,
    colors              TEXT,
    label               TEXT NOT NULL,
    method              TEXT NOT NULL CHECK (method IN ('archetype', 'fallback')),
    confidence          TEXT NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    cards_seen          INTEGER NOT NULL,
    conditions_met      INTEGER NOT NULL,
    conditions_unknown  INTEGER NOT NULL,
    evidence_json       TEXT,
    classified_at       TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- The user's own words about their own match, and the only source there is for
-- them. Not projector-owned.
--
-- Deliberately NO foreign key to matches. foreign_keys is ON, so a reference
-- here would make the rebuild's DELETE FROM matches fail outright, and the
-- whole point of a manual label is that it survives every rebuild. A row whose
-- match no longer exists is harmless: v_match_opponent joins to it, it never
-- drives the join.
-- ---------------------------------------------------------------------------
CREATE TABLE opponent_deck_override (
    match_id    TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- What the opponent showed us, reduced to colours and one signature card. This
-- is the last-resort label when no archetype matches, and it is a description
-- rather than a classification, so it stays in raw WUBRG letters.
--
-- card_events.seat is the raw OWNER seat, so a card of theirs that we stole
-- still counts as theirs and one of ours they took never does.
--
-- Lands and tokens are excluded by testing only the types half of the type
-- line, split on the em dash the card importer writes. Matching the whole line
-- would misread `Token Artifact — Lander`. Lands are excluded from the colours
-- because Arena reports every land as colourless anyway, and from the
-- signature slot because some alternate-art basics carry a rare rarity and
-- would win it outright.
-- ---------------------------------------------------------------------------
CREATE VIEW v_opponent_cards AS
WITH seen AS (
    SELECT m.match_id, c.name, c.rarity, c.colors, COUNT(*) AS times
      FROM card_events ce
      JOIN matches m ON m.match_id = ce.match_id
      JOIN cards   c ON c.grp_id   = ce.grp_id
     WHERE ce.seat = m.opponent_seat
       AND ce.grp_id IS NOT NULL
       AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                 'Land') = 0
       AND instr(substr(c.type_line, 1, instr(c.type_line || char(8212), char(8212))),
                 'Token') = 0
     GROUP BY m.match_id, c.name, c.rarity, c.colors
)
SELECT
    match_id,
    COUNT(*) AS cards_seen,
    (CASE WHEN MAX(colors LIKE '%W%') THEN 'W' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%U%') THEN 'U' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%B%') THEN 'B' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%R%') THEN 'R' ELSE '' END) ||
    (CASE WHEN MAX(colors LIKE '%G%') THEN 'G' ELSE '' END) AS colors,
    (SELECT s.name FROM seen s
      WHERE s.match_id = seen.match_id
      ORDER BY CASE s.rarity
                   WHEN 'mythic'   THEN 5
                   WHEN 'rare'     THEN 4
                   WHEN 'uncommon' THEN 3
                   WHEN 'common'   THEN 2
                   ELSE 1 END DESC,
               s.times DESC,
               s.name ASC
      LIMIT 1) AS signature_card
FROM seen
GROUP BY match_id;

-- ---------------------------------------------------------------------------
-- The label, in precedence order: what the user said, then what the rules
-- proved, then what the cards merely suggest.
--
-- opponent_key is what matchups group on, never the label. With colours in an
-- archetype name the same deck can be labelled differently from match to match
-- depending on which spells we happened to see, and grouping on the label
-- would split one matchup in two. A manual label keys on its own text, so two
-- matches the user names identically do merge.
-- ---------------------------------------------------------------------------
CREATE VIEW v_match_opponent AS
SELECT
    m.match_id,
    m.deck_id,
    COALESCE(
        o.label,
        a.label,
        COALESCE(NULLIF(v.colors, '') || ' ' || char(183) || ' ', '') || v.signature_card,
        'Unknown deck'
    ) AS opponent_label,
    COALESCE(
        'manual:' || o.label,
        'archetype:' || a.archetype_key,
        'colors:' || COALESCE(NULLIF(v.colors, '') || ' ' || char(183) || ' ', '')
                  || v.signature_card,
        'unknown'
    ) AS opponent_key,
    CASE WHEN o.match_id IS NOT NULL       THEN 'manual'
         WHEN a.method IS NOT NULL         THEN a.method
         WHEN v.signature_card IS NOT NULL THEN 'colors'
         ELSE 'unknown' END AS opponent_source,
    CASE WHEN o.match_id IS NOT NULL THEN 'high'
         ELSE COALESCE(a.confidence, 'unknown') END AS opponent_confidence,
    CASE WHEN o.match_id IS NOT NULL   THEN 4
         WHEN a.confidence = 'high'    THEN 3
         WHEN a.confidence = 'medium'  THEN 2
         WHEN a.confidence = 'low'     THEN 1
         ELSE 0 END AS confidence_rank,
    COALESCE(v.cards_seen, 0) AS opponent_cards_seen,
    a.archetype_key,
    a.archetype_name,
    a.evidence_json
FROM matches m
LEFT JOIN opponent_deck_override o ON o.match_id = m.match_id
LEFT JOIN opponent_archetype     a ON a.match_id = m.match_id
LEFT JOIN v_opponent_cards       v ON v.match_id = m.match_id;

-- ---------------------------------------------------------------------------
-- Winrate against each opponent deck. Completed matches only, counted the way
-- v_deck_winrate counts them, so a match still being played never moves a
-- percentage. Grouped by deck as well, because a matchup is a property of the
-- pair: one of your decks beating what another loses to is the thing worth
-- seeing, and it keeps the existing deck filter working unchanged.
--
-- The name shown for a group is the one from its best-evidenced match, which
-- is deterministic and beats picking an arbitrary member.
-- ---------------------------------------------------------------------------
CREATE VIEW v_matchup_winrate AS
WITH named AS (
    SELECT match_id, deck_id, opponent_key, confidence_rank,
           FIRST_VALUE(opponent_label) OVER (
               PARTITION BY opponent_key
               ORDER BY confidence_rank DESC, opponent_cards_seen DESC, match_id
           ) AS opponent_label
      FROM v_match_opponent
)
SELECT
    n.opponent_key,
    n.opponent_label,
    n.deck_id,
    MAX(n.confidence_rank) AS confidence_rank,
    COUNT(*) FILTER (WHERE m.result IN ('win', 'loss', 'draw')) AS matches_completed,
    COUNT(*) FILTER (WHERE m.result = 'win')                    AS matches_won,
    SUM(COALESCE(m.games_won, 0))                               AS games_won,
    SUM(COALESCE(m.games_lost, 0))                              AS games_lost,
    MAX(m.started_at)                                           AS last_played
FROM named n
JOIN matches m USING (match_id)
GROUP BY n.opponent_key, n.deck_id;
