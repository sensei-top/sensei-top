-- 037_mtgo_logged_at_separator.sql — repair for a database that already
-- applied the ORIGINAL (buggy) 036_mtgo_live.sql.
--
-- 036's UPDATE read `datetime(logged_at, 'localtime')`. Bare `datetime()`
-- returns a SPACE-separated string ('2026-09-14 12:42:44'), not the 'T'-
-- separated ISO shape every Arena timestamp uses
-- (`reader/segmenter.py::parse_header_timestamp`, and `reader/mtgo.py`'s own
-- already-correct `_mtime_iso`, which uses `isoformat()`). That inverted
-- Bug A rather than fixing it: `logged_at`/`started_at` are compared as TEXT
-- across sources (`v_current_match`'s `MAX(COALESCE(started_at,''))`,
-- `/api/matches`' `ORDER BY`, `/api/live`'s `MAX(logged_at)`), and ' ' (0x20)
-- sorts *below* every digit while 'T' (0x54) sorts *above* every digit — so a
-- space-form MTGO row now sorts as strictly OLDER than any same-instant
-- Arena row, and an MTGO match can never win `v_current_match` against a
-- same-day Arena match.
--
-- This migration only reshapes the separator — it does NOT re-run
-- `datetime(..., 'localtime')`, which already happened once in 036; doing it
-- again would shift the clock a second time. `strftime('%Y-%m-%dT%H:%M:%S',
-- x)` accepts both the space and 'T' forms as valid SQLite time strings, so
-- it is a pure reshape either way; the `LIKE '% %'` guard makes it a no-op
-- on a database whose 036 already produced the correct 'T' form (this
-- migration's own fix, or any row `_mtime_iso` wrote directly), rather than
-- touching every 'mtgo' row on every upgrade.
--
-- `matches.started_at`/`ended_at` for an MTGO match are a straight
-- passthrough of `raw_events.logged_at` at projection time
-- (`projector/mtgo/project.py`), so a match already projected under the
-- buggy 036 carries the same space-form value until the next full rebuild.
-- Repaired here directly too, rather than waiting on `project()` to run
-- again — the tab reads `matches.started_at` on every request and nothing
-- guarantees a rebuild fires before the next one.
UPDATE raw_events
   SET logged_at = strftime('%Y-%m-%dT%H:%M:%S', logged_at)
 WHERE source = 'mtgo' AND logged_at LIKE '% %';

UPDATE matches
   SET started_at = strftime('%Y-%m-%dT%H:%M:%S', started_at)
 WHERE source = 'mtgo' AND started_at LIKE '% %';

UPDATE matches
   SET ended_at = strftime('%Y-%m-%dT%H:%M:%S', ended_at)
 WHERE source = 'mtgo' AND ended_at LIKE '% %';
