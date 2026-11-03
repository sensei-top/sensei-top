"""Every AI feature: the opt-in Claude call, the prompts and the prose they bring back.

Core never imports this package. The tracker runs, and its tests pass, with
``ai/`` deleted; ``lint-imports`` holds that contract, and its
``ignore_imports`` list in ``pyproject.toml`` names the core edges still to cut
while the move is under way. What lives here may import core freely.

Core reaches it only through the three functions below, after
``importlib.util.find_spec`` finds it (docs/architecture.md, "Who may know
what"). The CLI imports this module on every command, so it imports nothing
at module level: each function imports what it hands over.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

    from fastapi import APIRouter

    from sensei_top.api.providers import Providers


def routers() -> list[APIRouter]:
    """The AI routers, which ``create_app`` mounts after core's and before
    the dashboard's catch-all; the order is the generated schema's."""
    from sensei_top.ai.routes import status

    return [status.router]


def providers() -> Providers:
    """The core seams this package fills (``api/providers.py``); called once
    per ``create_app``."""
    from sensei_top.api.providers import Providers

    return Providers()


def register_cli(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add the AI subcommands to ``build_parser``'s ``subparsers``, after
    core's."""
