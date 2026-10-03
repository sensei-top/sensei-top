-- 010_zone_card_detail.sql — widen v_turn_zones with the card detail `cards`
-- already stores but the view never surfaced: mana cost, type line, colours.
--
-- `cards` (003_current_match.sql) has held these columns from the start; only
-- `name` ever made it through the view. Surfacing the rest costs nothing new
-- to compute — it is a join that already happens — and is what a hints
-- feature needs to say anything about a card beyond its name (mana cost to
-- judge castability, type line to tell a land from a threat, colours to
-- reason about what a hand can represent).
--
-- No table change, so nothing to back-fill; the view is dropped and recreated
-- because SQLite views are frozen at creation, same as 007_board_detail.sql.
DROP VIEW v_turn_zones;

CREATE VIEW v_turn_zones AS
SELECT
    tz.match_id, tz.game_number, tz.turn_number, tz.zone, tz.idx,
    tz.instance_id, tz.grp_id, tz.card_types, tz.drawn_on_turn,
    tz.is_tapped, tz.power, tz.toughness,
    c.name AS card_name,
    c.mana_cost, c.type_line, c.colors,
    CASE WHEN m.self_seat IS NULL THEN NULL
         WHEN tz.seat = m.self_seat THEN 1
         ELSE 0 END AS is_self
FROM turn_zones tz
JOIN matches m USING (match_id)
LEFT JOIN cards c ON c.grp_id = tz.grp_id;
