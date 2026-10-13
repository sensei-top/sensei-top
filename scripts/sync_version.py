"""Write pyproject's version into the desktop shell's package.json.

    uv run python scripts/sync_version.py                  # write it
    uv run python scripts/sync_version.py --check          # exit 1 on a mismatch, write nothing
    uv run python scripts/sync_version.py --package PATH   # another package.json (tests)

``[project] version`` in ``pyproject.toml`` is the one source; the installer's
version comes from ``desktop/package.json``. Only the ``"version"`` value is
replaced, in place, so the file's formatting and key order are untouched. The
packaging workflow (``.github/workflows/desktop.yml``) runs ``--check`` before building.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
PACKAGE = ROOT / "desktop" / "package.json"

# The top-level key sits at two-space indent; nested "version" keys sit deeper.
VERSION_LINE = re.compile(r'^(  "version": )"[^"]*"(,?)$', re.MULTILINE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 on a mismatch")
    parser.add_argument("--package", type=Path, default=PACKAGE, help="package.json to use")
    args = parser.parse_args()

    wanted = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    text = args.package.read_text(encoding="utf-8")
    have = json.loads(text)["version"]

    if have == wanted:
        print(f"version {wanted}: in sync")
        return 0
    if args.check:
        print(
            f"version mismatch: pyproject.toml has {wanted}, {args.package.name} has {have}; "
            "run scripts/sync_version.py",
            file=sys.stderr,
        )
        return 1
    new, count = VERSION_LINE.subn(lambda m: f'{m.group(1)}"{wanted}"{m.group(2)}', text, count=1)
    if count != 1:
        print(f'no top-level "version" line found in {args.package}', file=sys.stderr)
        return 1
    args.package.write_text(new, encoding="utf-8", newline="")
    print(f"version {have} -> {wanted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
