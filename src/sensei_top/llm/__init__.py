"""The opt-in metered Claude call (AGENTS.md non-negotiable #5).

``config.py`` is the only place its credential is resolved, and
``client.py`` is the only module in the whole project that imports
``anthropic`` — nothing else needs to, because every route that wants written
prose calls through here. With no credential configured no client is ever
constructed: every generate route answers 503 and the dashboard falls back to
the copy prompt. ``provenance.py`` is the authored-prose tables' shared
timestamp and upsert, which pasted and imported answers write through too.

See docs/llm.md, "What calls out, and what it sends", and docs/llm.md,
"The fallback".
"""
