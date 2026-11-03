"""The import contract's source list must name every core module."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_contract_sources_are_every_core_module():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    (contract,) = [c for c in contracts if "sensei_top.ai" in c["forbidden_modules"]]
    package = ROOT / "src" / "sensei_top"
    core = set()
    for entry in package.iterdir():
        if entry.is_file() and entry.suffix == ".py":
            name = entry.stem
        elif entry.is_dir() and (entry / "__init__.py").exists():
            name = entry.name
        else:
            continue
        if name not in {"ai", "__init__", "__main__"}:
            core.add(f"sensei_top.{name}")
    assert set(contract["source_modules"]) == core, (
        "add a new core module to source_modules of the import contract in "
        "pyproject.toml (and remove one that no longer exists): "
        f"missing {sorted(core - set(contract['source_modules']))}, "
        f"stale {sorted(set(contract['source_modules']) - core)}"
    )
