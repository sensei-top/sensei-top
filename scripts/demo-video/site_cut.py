"""Cut the landing's demo video from one language's recorded segments.

    uv run python scripts/demo-video/site_cut.py --lang en|pt-br

Reads what record.ts wrote and shots.json's lengths. Writes, under site/, the
video, its captions, its chapter list and its poster. Exits 1 if the video
runs over the cap or off the timeline. assemble.py's cut is a different one.
Why it is built this way: docs/frontend-site.md, "The demo video".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
SITE = ROOT / "site"
SEGMENTS = ROOT / "demo" / "segments"
LOCALES = ROOT / "web" / "src" / "locales"

FADE = 0.3
FPS = 30
CAP = 5 * 1024 * 1024
HEIGHT = 1080
CRF = 24
POSTER_WIDTH = 1440
POSTER_QUALITY = 78
# Each shot's name on the page, as the dashboard writes it.
CHAPTER_KEYS = {
    "home": "shell.places.home",
    "live": "shell.places.live",
    "report": "shell.places.matches",
    "matchups": "decks.layout.tabs.matchups",
    "field": "shell.places.field",
}


@dataclass(frozen=True)
class Language:
    catalogue: str
    segments: Path
    poster: str
    caption_file: Path | None  # None: the captions are shots.json's own


LANGUAGES = {
    "en": Language("en", SEGMENTS, "demo-poster.webp", None),
    "pt-br": Language(
        "pt-BR", SEGMENTS / "pt-br", "demo-poster-pt-br.webp", HERE / "shots.pt-br.json"
    ),
}


@dataclass(frozen=True)
class Timed:
    id: str
    seconds: float
    fade_in: float  # where its crossfade begins; the shot is fully up FADE later
    start: float  # where it visibly starts
    end: float  # where the next shot's crossfade begins


def timeline(shots: list[dict]) -> tuple[list[Timed], float]:
    """Each product shot's times, and the video's length.

    A crossfade eats FADE from each join, and the shot has only fully arrived
    once it ends, so a chapter or a caption starts there: a seek to the fade's
    beginning would show the shot before.
    """
    fades = []
    at = 0.0
    for shot in shots:
        fades.append(at)
        at += shot["seconds"] - FADE
    total = at + FADE
    timed = []
    for i, shot in enumerate(shots):
        end = fades[i + 1] if i + 1 < len(shots) else total
        start = fades[i] + FADE if i else 0.0
        timed.append(
            Timed(shot["id"], shot["seconds"], round(fades[i], 3), round(start, 3), round(end, 3))
        )
    return timed, round(total, 3)


def product_shots() -> list[dict]:
    shots = json.loads((HERE / "shots.json").read_text(encoding="utf-8"))
    return [shot for shot in shots if shot["kind"] == "video"]


def captions_for(language: Language, shots: list[dict]) -> dict[str, str]:
    if language.caption_file is None:
        return {shot["id"]: shot["caption"] for shot in shots}
    return json.loads(language.caption_file.read_text(encoding="utf-8"))


def catalogue_label(catalogue: str, key: str) -> str:
    namespace, *path = key.split(".")
    node = json.loads((LOCALES / catalogue / f"{namespace}.json").read_text(encoding="utf-8"))
    for part in path:
        node = node[part]
    return node


def vtt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, minutes, whole = ms // 3_600_000, ms % 3_600_000 // 60_000, ms % 60_000 // 1000
    return f"{hours:02d}:{minutes:02d}:{whole:02d}.{ms % 1000:03d}"


def vtt(timed: list[Timed], captions: dict[str, str]) -> str:
    cues = [
        f"{i + 1}\n{vtt_time(shot.start)} --> {vtt_time(shot.end)}\n{captions[shot.id]}\n"
        for i, shot in enumerate(timed)
    ]
    return "WEBVTT\n\n" + "\n".join(cues)


def chapters(timed: list[Timed], total: float, catalogue: str) -> dict:
    return {
        "duration": total,
        "chapters": [
            {
                "id": shot.id,
                "label": catalogue_label(catalogue, CHAPTER_KEYS[shot.id]),
                "start": shot.start,
            }
            for shot in timed
        ],
    }


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def encode(segments: Path, timed: list[Timed], out: Path) -> None:
    """The five segments crossfaded into one H.264 file that starts as it downloads.

    record.ts's segments hold BT.601 values with no tag, and a browser reads an
    untagged HD video as BT.709, which shifts the palette against the poster:
    the values are converted and the file is tagged. The conversion is the
    chain's last step: a filter after it reads the tag and converts them again.
    """
    inputs: list[str] = []
    chain: list[str] = []
    for i, shot in enumerate(timed):
        inputs += ["-t", str(shot.seconds), "-i", str(segments / f"{shot.id}.mkv")]
        chain.append(
            f"[{i}:v]fps={FPS},scale=-2:{HEIGHT}:flags=lanczos,"
            f"format=yuv420p,setsar=1,settb=AVTB[s{i}]"
        )
    last = "s0"
    for i in range(1, len(timed)):
        chain.append(
            f"[{last}][s{i}]xfade=transition=fade:duration={FADE}:"
            f"offset={timed[i].fade_in:.3f}[x{i}]"
        )
        last = f"x{i}"
    chain.append(f"[{last}]colormatrix=bt601:bt709[out]")
    keyframes = ",".join(f"{shot.start:.3f}" for shot in timed)
    ffmpeg(
        *inputs,
        "-filter_complex",
        ";".join(chain),
        "-map",
        "[out]",
        "-c:v",
        "libx264",
        "-preset",
        "veryslow",
        "-crf",
        str(CRF),
        "-force_key_frames",
        keyframes,
        "-pix_fmt",
        "yuv420p",
        # -colorspace stays: without it the output's values shift against the
        # poster (test_the_video_opens_in_the_posters_colours). The primaries and
        # transfer flags do nothing on this ffmpeg; the bitstream filter tags them.
        "-colorspace",
        "bt709",
        "-color_range",
        "tv",
        "-bsf:v",
        "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1",
        "-an",
        "-movflags",
        "+faststart",
        str(out),
    )


def poster(segments: Path, out: Path) -> None:
    ffmpeg(
        "-i",
        str(segments / "home.mkv"),
        "-frames:v",
        "1",
        "-vf",
        f"scale={POSTER_WIDTH}:-2:flags=lanczos",
        "-c:v",
        "libwebp",
        "-quality",
        str(POSTER_QUALITY),
        str(out),
    )


def duration(path: Path) -> float:
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(done.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lang", choices=sorted(LANGUAGES), required=True)
    lang = parser.parse_args().lang
    language = LANGUAGES[lang]

    shots = product_shots()
    timed, total = timeline(shots)
    captions = captions_for(language, shots)
    video_dir = SITE / "video"
    video_dir.mkdir(exist_ok=True)

    # Encoded beside the real file and moved over it only once both checks
    # pass, so a language that fails leaves its old set as it was.
    mp4 = video_dir / f"demo-{lang}.mp4"
    scratch = video_dir / f"demo-{lang}.tmp.mp4"
    try:
        encode(language.segments, timed, scratch)
        size = scratch.stat().st_size
        length = duration(scratch)
        if abs(length - total) > 0.2:
            print(f"video: {length:.1f} s, the timeline says {total:.1f} s", file=sys.stderr)
            return 1
        if size >= CAP:
            print(f"video: {size} bytes, the cap is {CAP}", file=sys.stderr)
            return 1
        scratch.replace(mp4)
    finally:
        scratch.unlink(missing_ok=True)

    (video_dir / f"demo-{lang}.vtt").write_text(vtt(timed, captions), encoding="utf-8")
    (video_dir / f"demo-{lang}.chapters.json").write_text(
        json.dumps(chapters(timed, total, language.catalogue), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    poster_path = SITE / "img" / language.poster
    poster(language.segments, poster_path)
    print(f"{lang}: {length:.1f} s, video {size} bytes, poster {poster_path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
