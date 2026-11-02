"""Build the two demo databases the video records, from demo_db.py's copy.

    uv run python scripts/demo-video/seed.py [--live MATCH_ID] [--live-cut ROW]

Reads ``~/.local/share/sensei-top-demo/base.db`` (``demo_db.py --seed 1``) and
writes ``uncut.db``, ``live.db``, ``card_images/`` and ``manifest.json`` beside
it. The Live copy needs ``demo_db.py --from data/sensei-top.db --live``, which
opens the real database ``mode=ro``; nothing else touches it.

After the projection, every opponent's pseudonym becomes ``Opponent N``, in
order of first match, in every text column, raw events included. It comes after
because a handle with a space may not survive MTGO's parser, so these copies are
never rebuilt again. The final scan is demo_db's own, for the pseudonyms.

Prints counts and the chosen ids only. A failure here leaves the copies on disk,
but they already passed demo_db.py's check.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path.home() / ".local/share/sensei-top-demo"
REAL = ROOT / "data/sensei-top.db"
SEED = 1
SELF = "Deshi"
PSEUDONYM = re.compile(r"(?<![\w#])[A-Z][a-z]+#\d{5}(?!\w)")
MIN_LAST_GAME_TURNS = 8
LIVE_MINUTES_IN = 35


def load_demo_db():
    spec = importlib.util.spec_from_file_location("demo_db", ROOT / "scripts/demo_db.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_db"] = module
    spec.loader.exec_module(module)
    return module


def env() -> dict[str, str]:
    config = OUT / "empty-config"
    config.mkdir(exist_ok=True)
    return {**os.environ, "MTGO_HANDLE": SELF, "XDG_CONFIG_HOME": str(config)}


def reflink(source: Path, target: Path) -> None:
    subprocess.run(["cp", "-a", "--reflink=auto", str(source), str(target)], check=True)


def project(db: Path) -> None:
    subprocess.run(
        ["uv", "run", "sensei-top", "--db", str(db), "project"], check=True, env=env(), cwd=ROOT
    )


def choose_live_match(db: Path) -> str:
    """The newest ladder match that went to three games, with a named opponent
    deck and a last game long enough to have a library worth reading."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    row = conn.execute(
        """
        SELECT m.match_id
        FROM matches m
        JOIN opponent_archetype a ON a.match_id = m.match_id
        WHERE m.source = 'arena' AND m.event_id = 'Traditional_Ladder'
          AND m.games_won + m.games_lost = 3
          AND a.archetype_name IS NOT NULL AND a.confidence = 'high'
          AND (SELECT MAX(t.turn_number) FROM turns t
               WHERE t.match_id = m.match_id AND t.game_number = 3) >= ?
        ORDER BY m.started_at DESC LIMIT 1
        """,
        (MIN_LAST_GAME_TURNS,),
    ).fetchone()
    conn.close()
    if row is None:
        raise SystemExit("no match fits the Live shot")
    return row[0]


def rename_terms(db: Path, demo_db) -> dict[str, str]:
    """Pseudonym -> ``Opponent N``: those in ``matches`` by first match, then
    any other a text column names (a player in a log who never became a match)."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    mapping: dict[str, str] = {}

    def add(name: str) -> None:
        key = name.lower()
        if key not in mapping and not name.startswith(SELF):
            mapping[key] = f"Opponent {len(mapping) + 1}"

    for (name,) in conn.execute(
        "SELECT opponent_name FROM matches WHERE opponent_name IS NOT NULL "
        "GROUP BY opponent_name ORDER BY MIN(started_at)"
    ):
        if PSEUDONYM.fullmatch(name):
            add(name)
    for table in demo_db._tables(conn):
        for column in demo_db._columns(conn, table):
            c = demo_db._q(column)
            sql = f"SELECT {c} FROM {demo_db._q(table)} WHERE typeof({c}) = 'text'"
            sql += demo_db._mtgo_filter(table, column)
            for (value,) in conn.execute(sql):
                for name in PSEUDONYM.findall(value):
                    add(name)
    for source, payload in conn.execute(
        "SELECT source, payload FROM raw_events WHERE source IN ('mtgo', 'mtgo_deck')"
    ):
        for text in demo_db._decoded_texts(source, payload):
            for name in PSEUDONYM.findall(text):
                add(name)
    conn.close()
    return mapping


def rename(db: Path, mapping: dict[str, str], demo_db) -> None:
    terms = [demo_db.DemoTerm("opponent", key, True) for key in mapping]
    matcher = demo_db.Matcher(terms, mapping)
    conn = sqlite3.connect(db)
    try:
        demo_db.rewrite_database(conn, matcher)
        found = demo_db.check_database(conn, matcher)
        if found:
            raise SystemExit(f"{db.name}: pseudonyms left after the rename: {sum(found.values())}")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


def facts(uncut: Path, live: Path) -> dict[str, object]:
    conn = sqlite3.connect(f"file:{uncut}?mode=ro", uri=True)
    last = conn.execute("SELECT MAX(started_at) FROM matches").fetchone()[0]
    conn.close()
    conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    match_id, started = conn.execute("SELECT match_id, started_at FROM v_current_match").fetchone()
    conn.close()
    # started_at is what the Live header compares with the browser's clock.
    moment = (datetime.fromisoformat(started) + timedelta(minutes=LIVE_MINUTES_IN)).isoformat()
    return {
        "uncut_last_match": last,
        "live_match": match_id,
        "live_started": started,
        "live_clock": moment,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", help="the Live match, instead of choosing one")
    parser.add_argument("--live-cut", type=int, help="the raw event to cut the Live match at")
    parser.add_argument("--keep-uncut", action="store_true", help="reuse uncut.db as it stands")
    args = parser.parse_args()

    base, uncut, live = OUT / "base.db", OUT / "uncut.db", OUT / "live.db"
    demo_db = load_demo_db()

    if args.keep_uncut and uncut.exists():
        print("uncut.db kept")
    else:
        uncut.unlink(missing_ok=True)
        reflink(base, uncut)
        project(uncut)

    # The pseudonyms are the same in both: demo_db draws them from the seed,
    # before the cut, over the same terms. Read them before the rename below.
    live_id = args.live or (choose_live_match(uncut) if not args.keep_uncut else None)
    if live_id is None:
        raise SystemExit("--keep-uncut needs --live: the rename has taken the names")
    print(f"live match: {live_id}")

    for name in ("live.db", "live.db-wal", "live.db-shm"):
        (OUT / name).unlink(missing_ok=True)
    command = ["uv", "run", "python", "scripts/demo_db.py", "--from", str(REAL), "--to", str(live)]
    command += ["--live", live_id, "--seed", str(SEED)]
    if args.live_cut is not None:
        command += ["--live-cut", str(args.live_cut)]
    subprocess.run(command, check=True, cwd=ROOT)
    project(live)

    # Both copies' names, the Live copy's first read for a real database that
    # gained a match since base.db was written.
    mapping = rename_terms(uncut, demo_db)
    for name in rename_terms(live, demo_db):
        if name not in mapping and not name.startswith(SELF.lower()):
            mapping[name] = f"Opponent {len(mapping) + 1}"
    print(f"opponents renamed: {len(mapping)}")
    rename(uncut, mapping, demo_db)
    rename(live, mapping, demo_db)

    images = OUT / "card_images"
    if not images.exists():
        shutil.copytree(ROOT / "data/card_images", images, copy_function=shutil.copy2)

    manifest = facts(uncut, live)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
