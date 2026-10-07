#!/bin/sh
# Serves the dashboard for the spike on 8765 from a snapshot of the real
# database, so the spike never opens data/sensei-top.db and never collides
# with the real `serve --watch` on 8000. No watcher: nothing is ingested.
set -eu
repo="$(cd "$(dirname "$0")/../.." && pwd)"
snap="${XDG_CACHE_HOME:-$HOME/.cache}/sensei-top-spike/snapshot.db"
mkdir -p "$(dirname "$snap")"
if [ ! -f "$snap" ]; then
  sqlite3 "$repo/data/sensei-top.db" ".backup '$snap'"
fi
cd "$repo"
exec uv run sensei-top --db "$snap" serve --port 8765
