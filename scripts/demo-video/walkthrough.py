"""Build the LinkedIn walkthrough PDF, since a profile section can't play video.

    uv run python scripts/demo-video/walkthrough.py

Run after assemble.py, whose demo/segments/<id>.mp4 it reads. One page per shot in
PAGES, 1920x1080, caption burned in larger than the video's. Writes
demo/sensei-top-walkthrough.pdf.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo"
SEGMENTS = DEMO / "segments"
LIMIT = 10 * 1024 * 1024
# Nine shots, eight pages at most: Matchups is the one left out. The second number
# is where in the shot its still is taken, after any zoom has settled.
PAGES = {
    "title": 2.0,
    "home": 8.0,
    "live": 9.5,
    "report": 9.5,
    "field": 9.0,
    "arch": 11.0,
    "how-built": 5.0,
    "end": 4.0,
}
STYLE = (
    "FontName=DejaVu Sans,FontSize=14,PrimaryColour=&H00F8F3F2,BackColour=&H30140C0B,"
    "BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=12"
).replace(",", r"\,")


def main() -> int:
    shots = {
        s["id"]: s for s in json.loads(Path(__file__).with_name("shots.json").read_text("utf-8"))
    }
    magick = shutil.which("magick")
    if magick is None:
        print("magick is not installed", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(dir=SEGMENTS) as tmp:
        work = Path(tmp)
        pages: list[Path] = []
        for number, (shot_id, at) in enumerate(PAGES.items(), 1):
            srt = work / f"{number}.srt"
            srt.write_text(
                f"1\n00:00:00,000 --> 00:00:10,000\n{shots[shot_id]['caption']}\n", "utf-8"
            )
            page = work / f"{number}.png"
            subprocess.run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    str(at),
                    "-i",
                    str(SEGMENTS / f"{shot_id}.mp4"),
                    "-vf",
                    f"setpts=PTS-STARTPTS,subtitles={srt}:force_style='{STYLE}'",
                    "-frames:v",
                    "1",
                    str(page),
                ],
                check=True,
            )
            pages.append(page)
        pdf = DEMO / "sensei-top-walkthrough.pdf"
        for quality in (92, 85, 75, 65):
            subprocess.run(
                [
                    magick,
                    *map(str, pages),
                    "-units",
                    "PixelsPerInch",
                    "-density",
                    "72",
                    "-compress",
                    "jpeg",
                    "-quality",
                    str(quality),
                    str(pdf),
                ],
                check=True,
            )
            if pdf.stat().st_size < LIMIT:
                print(
                    f"pdf: {len(pages)} pages, quality {quality}, {pdf.stat().st_size / 1e6:.1f} MB"
                )
                return 0
    print("pdf: still over the limit at the lowest quality", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
