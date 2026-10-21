"""Count Sensei Top's downloads from GitHub's release asset counters.

The site's Download buttons redirect to these same files (`worker/download.mjs`),
so GitHub's counters are the one place a download is counted. Only the
installers count as downloads; the updater feeds and blockmaps are separated
out, and the feeds on the newest release give the active-install estimate.
Reads the public API without a token (60 requests an hour is plenty).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime

RELEASES_API = "https://api.github.com/repos/sensei-top/sensei-top/releases?per_page=100"
FIRST_PUBLIC = "v1.0.0"
ROW = "{:<9} {:<11} {:>5} {:>5} {:>6} {:>4} {:>10} {:>6}"
COLUMNS = ("release", "published", "days", "win", "appimg", "tar", "feeds w/l", "blkmap")


def kind(name: str) -> str:
    """Which column an asset belongs to."""
    if name.endswith(".exe"):
        return "windows"
    if name.endswith(".AppImage"):
        return "appimage"
    if name.endswith(".tar.gz"):
        return "tarball"
    if name == "latest.yml":
        return "feed_win"
    if name == "latest-linux.yml":
        return "feed_linux"
    if name.endswith(".blockmap"):
        return "blockmap"
    return "other"


def fetch() -> list[dict]:
    headers = {"Accept": "application/vnd.github+json"}
    request = urllib.request.Request(RELEASES_API, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def tally(release: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for asset in release["assets"]:
        column = kind(asset["name"])
        counts[column] = counts.get(column, 0) + asset["download_count"]
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--since", default=FIRST_PUBLIC, help=f"first release to count (default {FIRST_PUBLIC})"
    )
    args = parser.parse_args()

    releases = [r for r in fetch() if not r["draft"] and not r["prerelease"]]
    releases.sort(key=lambda r: r["published_at"])
    tags = [r["tag_name"] for r in releases]
    if args.since not in tags:
        print(f"no release {args.since}; releases are {', '.join(tags)}", file=sys.stderr)
        return 1
    counted = releases[tags.index(args.since) :]
    now = datetime.now(UTC)

    print(f"Downloads since {args.since}, read {now:%Y-%m-%d %H:%M} UTC\n")
    header = ROW.format(*COLUMNS)
    print(header)
    print("-" * len(header))
    totals = {"windows": 0, "appimage": 0, "tarball": 0}
    for release in reversed(counted):
        c = tally(release)
        published = datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
        days = (now - published).total_seconds() / 86400
        for column in totals:
            totals[column] += c.get(column, 0)
        feeds = f"{c.get('feed_win', 0)}/{c.get('feed_linux', 0)}"
        print(
            ROW.format(
                release["tag_name"],
                f"{published:%Y-%m-%d}",
                f"{days:.1f}",
                *(c.get(column, 0) for column in ("windows", "appimage", "tarball")),
                feeds,
                c.get("blockmap", 0),
            )
        )
        if c.get("other"):
            print(f"  + {c['other']} on assets this script does not know; check the release")

    installers = sum(totals.values())
    print(
        f"\nInstallers since {args.since}: {installers} "
        f"(Windows {totals['windows']}, AppImage {totals['appimage']}, tarball {totals['tarball']})"
    )

    newest = counted[-1]
    c = tally(newest)
    published = datetime.fromisoformat(newest["published_at"].replace("Z", "+00:00"))
    days = (now - published).total_seconds() / 86400
    feeds = c.get("feed_win", 0) + c.get("feed_linux", 0)
    if days < 1:
        print(f"Active-install estimate: {newest['tag_name']} is under a day old; read tomorrow")
    else:
        print(
            f"Active-install estimate: {feeds} feed reads on {newest['tag_name']} "
            f"over {days:.1f} days = about {feeds / days:.1f} a day (an upper bound; see SKILL.md)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
