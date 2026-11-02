"""Assemble the demo video from what capture.ts and record.ts wrote.

    uv run python scripts/demo-video/assemble.py

shots.json is the one timeline: it drives the segments, the crossfades and the
captions. Writes demo/captions.srt, demo/sensei-top-demo-1080p.mp4,
demo/sensei-top-demo.gif and demo/stills/ (one frame per shot, to look at).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo"
SEGMENTS = DEMO / "segments"
FADE = 0.3
FPS = 30
ENCODE = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-an"]
GIF_LIMIT = 10 * 1024 * 1024
GIF_SHOTS = ("home", "live", "report")
ARCH_STEP_SECONDS = 1.1
CAPTION_STYLE = (
    "FontName=DejaVu Sans,FontSize=12,PrimaryColour=&H00F8F3F2,OutlineColour=&H00140C0B,"
    "BackColour=&H30140C0B,BorderStyle=4,Outline=0,Shadow=0,Alignment=2,MarginV=12"
)


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def card_segment(image: Path, seconds: float, out: Path) -> None:
    run(
        "-loop",
        "1",
        "-framerate",
        str(FPS),
        "-t",
        str(seconds),
        "-i",
        str(image),
        *ENCODE,
        "-crf",
        "14",
        str(out),
    )


def steps_segment(seconds: float, out: Path) -> None:
    """The architecture card, its stages lighting up one at a time."""
    images = sorted(SEGMENTS.glob("card-arch-*.png"))
    last = seconds - ARCH_STEP_SECONDS * (len(images) - 1)
    inputs: list[str] = []
    for i, image in enumerate(images):
        length = last if i == len(images) - 1 else ARCH_STEP_SECONDS
        inputs += ["-loop", "1", "-framerate", str(FPS), "-t", str(length), "-i", str(image)]
    graph = "".join(f"[{i}:v]" for i in range(len(images))) + f"concat=n={len(images)}:v=1:a=0[out]"
    run(*inputs, "-filter_complex", graph, "-map", "[out]", *ENCODE, "-crf", "14", str(out))


def video_segment(source: Path, seconds: float, out: Path) -> None:
    run(
        "-i",
        str(source),
        "-t",
        str(seconds),
        "-vf",
        f"fps={FPS},scale=1920:1080",
        *ENCODE,
        "-crf",
        "14",
        str(out),
    )


def timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    hours, minutes, whole = ms // 3_600_000, ms % 3_600_000 // 60_000, ms % 60_000 // 1000
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{ms % 1000:03d}"


def main() -> int:
    shots = json.loads((Path(__file__).with_name("shots.json")).read_text(encoding="utf-8"))
    parts: list[Path] = []
    for shot in shots:
        out = SEGMENTS / f"{shot['id']}.mp4"
        if shot["kind"] == "card":
            card_segment(SEGMENTS / f"card-{shot['id']}.png", shot["seconds"], out)
        elif shot["kind"] == "steps":
            steps_segment(shot["seconds"], out)
        else:
            video_segment(SEGMENTS / f"{shot['id']}.mkv", shot["seconds"], out)
        parts.append(out)

    # A crossfade eats FADE from each join, so each shot starts FADE earlier
    # than the sum of the lengths before it.
    starts: list[float] = []
    at = 0.0
    for shot in shots:
        starts.append(at)
        at += shot["seconds"] - FADE
    total = at + FADE

    srt = []
    for i, shot in enumerate(shots):
        end = starts[i + 1] if i + 1 < len(shots) else total
        srt.append(
            f"{i + 1}\n{timestamp(starts[i] + FADE)} --> {timestamp(end)}\n{shot['caption']}\n"
        )
    captions = DEMO / "captions.srt"
    captions.write_text("\n".join(srt), encoding="utf-8")

    inputs: list[str] = []
    for part in parts:
        inputs += ["-i", str(part)]
    chain = []
    last = "0:v"
    for i in range(1, len(parts)):
        chain.append(
            f"[{last}][{i}:v]xfade=transition=fade:duration={FADE}:offset={starts[i]:.3f}[x{i}]"
        )
        last = f"x{i}"
    style = CAPTION_STYLE.replace(",", r"\,")
    chain.append(f"[{last}]subtitles={captions}:force_style='{style}',format=yuv420p[out]")
    mp4 = DEMO / "sensei-top-demo-1080p.mp4"
    run(
        *inputs,
        "-filter_complex",
        ";".join(chain),
        "-map",
        "[out]",
        *ENCODE,
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(mp4),
    )

    length = float(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "csv=p=0",
                str(mp4),
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    if abs(length - total) > 0.2:
        print(f"video: {length:.1f} s, the timeline says {total:.1f} s", file=sys.stderr)
        return 1

    stills = DEMO / "stills"
    stills.mkdir(exist_ok=True)
    for i, shot in enumerate(shots):
        # Late in the shot, after its zoom and well clear of both fades.
        run(
            "-ss",
            f"{starts[i] + shot['seconds'] * 0.6:.2f}",
            "-i",
            str(mp4),
            "-frames:v",
            "1",
            str(stills / f"{i + 1}-{shot['id']}.png"),
        )

    ids = [shot["id"] for shot in shots]
    first = ids.index(GIF_SHOTS[0])
    final = ids.index(GIF_SHOTS[-1])
    # Clear of the fades into the title card's and out to the next shot's.
    gif_start = starts[first] + FADE
    gif_length = starts[final] + shots[final]["seconds"] - FADE - gif_start
    gif = DEMO / "sensei-top-demo.gif"
    for fps, colors in ((10, 128), (8, 96), (6, 64)):
        graph = (
            f"fps={fps},scale=960:-1:flags=lanczos,split[a][b];"
            f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
            "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle"
        )
        run(
            "-ss",
            f"{gif_start:.2f}",
            "-t",
            f"{gif_length:.2f}",
            "-i",
            str(mp4),
            "-filter_complex",
            graph,
            str(gif),
        )
        if gif.stat().st_size < GIF_LIMIT:
            print(f"gif: {gif_length:.1f} s at {fps} fps, {colors} colours")
            break
    else:
        print("gif: still over the limit at the lowest setting", file=sys.stderr)
        return 1

    print(f"video: {total:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
