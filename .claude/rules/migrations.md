---
paths:
  - "src/sensei_top/migrations/**"
  - "src/sensei_top/db.py"
---

# Working in `migrations/` and `db.py`: when a migration applies

Everything `serve` opens later uses `connect()`, so a new migration is **pending** until `serve --watch` restarts — `docs/architecture.md`, "Storage". Check `SELECT MAX(version) FROM schema_version` on a read-only connection rather than assuming. The API never migrates.
