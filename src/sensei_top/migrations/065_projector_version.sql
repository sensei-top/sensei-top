-- 065_projector_version.sql — which projector wrote the derived rows.
--
-- projection_state.projector_version holds projector.PROJECTOR_VERSION as of
-- the watcher's last rebuild. A watcher that finds a different value, or NULL
-- (a row written before this column existed; a rebuild by an older build
-- leaves the column as it was), treats its first poll as dirty and rebuilds
-- once, so a fixed projector's old rows don't wait for Arena or MTGO to write
-- again.
-- Bookkeeping, not projected data: project() never touches it.
ALTER TABLE projection_state ADD COLUMN projector_version INTEGER;
