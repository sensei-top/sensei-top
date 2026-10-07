"""The one opt-in metered call this project makes.

AGENTS.md non-negotiable #5 used to forbid any call to a paid API at all;
it now permits exactly one, gated on the user configuring a credential
themselves. ``config.py`` is the only place that credential is resolved, and
``client.py`` is the only module in the whole project that imports
``anthropic`` — nothing else needs to, because every route that wants written
prose calls through here. See ``docs/llm.md`` for the full design: what gets
sent, what it costs, and what happens with nothing configured (exactly what
happened before this package existed).
"""
