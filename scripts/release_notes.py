"""Print one version's section of CHANGELOG.md: the text of a release's notes.

    uv run python scripts/release_notes.py                     # pyproject's version
    uv run python scripts/release_notes.py --version 0.7.0     # another version
    uv run python scripts/release_notes.py --changelog PATH    # another file (tests)

The changelog is in Keep a Changelog form: each release is a ``## [X.Y.Z] -
date`` heading. The section is what follows that heading up to the next ``## ``
heading, without the heading itself (the release's title is its tag) and
without the link references that close the file. Exit 1, with a message on
stderr, when the version has no section. That is the case until the release
branch renames ``## [Unreleased]`` to the version, so the release job cannot
publish notes that were never written. ``Unreleased`` is not a version and is
never printed. The release workflow (``.github/workflows/desktop.yml``) writes
this output to the file ``gh release create`` reads.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"

VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")
HEADING = re.compile(r"^## ")
# `[0.7.0]: https://...`, the reference definitions Keep a Changelog ends the file with.
LINK_REFERENCE = re.compile(r"^\[[^\]]+\]:\s+\S+\s*$")


def section(text: str, version: str) -> str | None:
    """The body under ``## [version]``, or None when there is no such heading."""
    heading = re.compile(rf"^## \[{re.escape(version)}\](?:\s|$)")
    body: list[str] | None = None
    for line in text.splitlines():
        if body is None:
            if heading.match(line):
                body = []
        elif HEADING.match(line):
            break
        else:
            body.append(line)
    if body is None:
        return None
    while body and (not body[-1].strip() or LINK_REFERENCE.match(body[-1])):
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    return "\n".join(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", help="the version to print (default: pyproject.toml's)")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG, help="CHANGELOG.md to read")
    args = parser.parse_args(argv)

    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    version = args.version or pyproject["project"]["version"]
    if not VERSION.fullmatch(version):
        print(f"{version!r} is not a version number; Unreleased has no notes", file=sys.stderr)
        return 1
    text = args.changelog.read_text(encoding="utf-8")
    body = section(text, version)
    if body is None:
        print(
            f"no section for {version} in {args.changelog.name}: on the release branch, rename "
            f"'## [Unreleased]' to '## [{version}] - <date>' (docs/branching.md, 'A release')",
            file=sys.stderr,
        )
        return 1
    if not body:
        print(f"the section for {version} in {args.changelog.name} is empty", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
