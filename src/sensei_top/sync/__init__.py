"""What the cloud backup sends: one payload per match, built from the
projected tables, served by ``GET /api/sync/payloads``. Core, never
``sensei_top.ai``; it reads the database and calls nothing outside the
machine (the shell's main process does the upload).
"""

from sensei_top.sync.payloads import SCHEMA_VERSION, MatchPayload, build_payloads, canonical_json

__all__ = ["SCHEMA_VERSION", "MatchPayload", "build_payloads", "canonical_json"]
