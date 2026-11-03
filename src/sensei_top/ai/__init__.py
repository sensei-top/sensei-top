"""Every AI feature: the opt-in Claude call, the prompts and the prose they bring back.

Core never imports this package. The tracker runs, and its tests pass, with
``ai/`` deleted; ``lint-imports`` holds that contract, and its
``ignore_imports`` list in ``pyproject.toml`` names the core edges still to cut
while the move is under way. What lives here may import core freely.
"""
