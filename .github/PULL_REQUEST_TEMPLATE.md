## What this changes

## Checks

- A parsing rule changed here has a fixture-backed test, and the expected values come from reading the log, not from running the code.
- If a player sees the difference, `CHANGELOG.md` has a line under Unreleased.
- `uv run python scripts/privacy_scan.py` is clean, and every commit is signed off (`git commit -s`).
