"""Draw the roadmap visual, one self-contained SVG per language, text outlined.

    uv run --no-project --with fonttools --with brotli --with uharfbuzz \
        python scripts/roadmap_svg.py [OUT_DIR]

OUT_DIR defaults to site/img/. An SVG in an <img> cannot load Inter, hence the outlines.
Words are the landings' #roadmap sections', verbatim, apart from a list item's closing
full stop on a Later chip and a label's closing colon.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "site" / "fonts" / "inter-latin-wght-normal.woff2"

PLANE = "#12141f"
LINE = "#2a2d3f"
CHIP = "#4a4f6e"
NODE = "#1a1d2c"
INK = "#f2f3f8"
INK_2 = "#b9bdd0"
MUTED = "#989db5"
ACCENT = "#f4b6e4"
ON_ACCENT = "#1a1020"

WIDTH = 1200
PAD = 56
FEATURES = {"cv11": True, "ss03": True}


@dataclass(frozen=True)
class Copy:
    lang: str
    title: str
    next_label: str
    later_label: str
    dates: str
    next_items: tuple[str, ...]
    later_items: tuple[str, ...]


EN = Copy(
    lang="en",
    title="Roadmap",
    next_label="Next, in this order",
    later_label="Later, in no set order",
    dates="Dates are not promised.",
    next_items=(
        "An overlay for Arena.",
        "Sideboard guides, with no generated answers.",
        "Win rates per card, from your own games.",
        "Your matches as a CSV file, and every table column explained.",
        "Magic Online on the Live page.",
    ),
    later_items=(
        "A page that shows the tracker is reading your log",
        "Written guides with any model",
        "macOS, Arena only",
        "Historic, Explorer and Timeless",
    ),
)
PT = Copy(
    lang="pt-BR",
    title="Roadmap",
    next_label="A seguir, nesta ordem",
    later_label="Mais tarde, sem ordem definida",
    dates="Nenhuma data é prometida.",
    next_items=(
        "Um overlay para o Arena.",
        "Guias de sideboard, sem respostas geradas.",
        "Taxas de vitórias por card, a partir dos seus próprios jogos.",
        "Suas partidas em um arquivo CSV, e cada coluna das tabelas explicada.",
        "Magic Online na página Ao vivo.",
    ),
    later_items=(
        "Uma página que mostra que o tracker está lendo o seu log",
        "Guias escritos com qualquer modelo",
        "macOS, só para o Arena",
        "Os formatos Histórico, Explorador e Atemporal",
    ),
)


class Face:
    """One static weight of Inter: shapes text with kerning, hands back outlines."""

    def __init__(self, weight: int) -> None:
        font = TTFont(FONT)
        static = instancer.instantiateVariableFont(font, {"wght": weight})
        static.flavor = None
        buffer = io.BytesIO()
        static.save(buffer)
        self.font = static
        self.glyph_set = static.getGlyphSet()
        self.order = static.getGlyphOrder()
        self.upem = static["head"].unitsPerEm
        self.hb_font = hb.Font(hb.Face(buffer.getvalue()))
        self.weight = weight

    def shape(self, text: str) -> list[tuple[str, float]]:
        """(glyph name, pen x in font units) per glyph, then the total advance last."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb_font, buf, FEATURES)
        placed: list[tuple[str, float]] = []
        x = 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions, strict=True):
            placed.append((self.order[info.codepoint], x + pos.x_offset))
            x += pos.x_advance
        placed.append(("", x))
        return placed

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        placed = self.shape(text)
        return placed[-1][1] * size / self.upem + tracking * size * (len(placed) - 2)

    def path(self, glyph: str) -> str:
        pen = SVGPathPen(self.glyph_set, ntos=lambda v: str(round(v)))
        self.glyph_set[glyph].draw(pen)
        return pen.getCommands()


class Canvas:
    def __init__(self, faces: dict[int, Face]) -> None:
        self.faces = faces
        self.defs: dict[tuple[int, str], str] = {}
        self.body: list[str] = []

    def text(
        self,
        text: str,
        x: float,
        y: float,
        size: float,
        weight: int,
        fill: str,
        anchor: str = "start",
        tracking: float = 0.0,
    ) -> None:
        face = self.faces[weight]
        width = face.width(text, size, tracking)
        if anchor == "end":
            x -= width
        elif anchor == "middle":
            x -= width / 2
        scale = size / face.upem
        uses: list[str] = []
        for index, (glyph, pen_x) in enumerate(face.shape(text)[:-1]):
            commands = face.path(glyph)
            if not commands:
                continue
            key = (weight, glyph)
            ident = self.defs.setdefault(key, f"g{len(self.defs)}")
            px = x + pen_x * scale + tracking * size * index
            uses.append(f'<use href="#{ident}" x="{px / scale:.0f}"/>')
        self.body.append(
            f'<g fill="{fill}" transform="translate(0 {y:.2f}) scale({scale:.5f} {-scale:.5f})">'
            + "".join(uses)
            + "</g>"
        )

    def raw(self, element: str) -> None:
        self.body.append(element)

    def glyph_defs(self) -> str:
        return "".join(
            f'<path id="{ident}" d="{self.faces[weight].path(glyph)}"/>'
            for (weight, glyph), ident in self.defs.items()
        )


def wrap(face: Face, text: str, size: float, limit: float) -> list[str]:
    """Greedy, then the narrowest measure that keeps the line count: no orphan last line."""
    lines = _greedy(face, text, size, limit)
    while limit > 0:
        limit -= 4
        trial = _greedy(face, text, size, limit)
        if len(trial) > len(lines):
            break
        lines = trial
    return lines


def _greedy(face: Face, text: str, size: float, limit: float) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and face.width(trial, size) > limit:
            lines.append(current)
            current = word
        else:
            current = trial
    lines.append(current)
    return lines


def draw(copy: Copy, faces: dict[int, Face]) -> str:
    canvas = Canvas(faces)
    body_face = faces[450]
    inner = WIDTH - 2 * PAD

    canvas.text(copy.title, PAD, 92, 38, 600, INK, tracking=-0.022)
    canvas.text(copy.dates, WIDTH - PAD, 90, 20, 450, MUTED, anchor="end")

    # Next: an ordered rail, the one place in the drawing with a direction.
    y = 156
    canvas.text(copy.next_label, PAD, y, 21, 600, ACCENT)
    rail_y = y + 58
    gap = 28
    steps = len(copy.next_items)
    column = (inner - gap * (steps - 1)) / steps
    radius = 22
    xs = [PAD + index * (column + gap) for index in range(steps)]
    canvas.raw(
        f'<path d="M{xs[0] + radius:.1f} {rail_y}H{WIDTH - PAD}" stroke="{CHIP}" stroke-width="2"/>'
    )
    item_size = 21
    leading = 30
    deepest = 0
    for index, (x, item) in enumerate(zip(xs, copy.next_items, strict=True)):
        first = index == 0
        canvas.raw(
            f'<circle cx="{x + radius:.1f}" cy="{rail_y}" r="{radius}" '
            f'fill="{ACCENT if first else NODE}" '
            f'stroke="{ACCENT if first else CHIP}" stroke-width="2"/>'
        )
        canvas.text(
            str(index + 1),
            x + radius,
            rail_y + 7.5,
            21,
            600,
            ON_ACCENT if first else INK,
            anchor="middle",
        )
        lines = wrap(body_face, item, item_size, column)
        deepest = max(deepest, len(lines))
        for number, line in enumerate(lines):
            canvas.text(line, x, rail_y + 62 + number * leading, item_size, 450, INK)
    bottom = rail_y + 62 + (deepest - 1) * leading

    # Later: chips that wrap, no rail and no numbers, since no order is promised.
    y = bottom + 68
    canvas.raw(f'<path d="M{PAD} {y - 34}H{WIDTH - PAD}" stroke="{LINE}" stroke-width="1"/>')
    y += 14
    canvas.text(copy.later_label, PAD, y, 21, 600, INK_2)
    chip_h = 52
    chip_gap = 14
    chip_pad = 22
    size = 20
    x = PAD
    top = y + 26
    for item in copy.later_items:
        width = body_face.width(item, size) + 2 * chip_pad
        if x > PAD and x + width > WIDTH - PAD:
            x = PAD
            top += chip_h + chip_gap
        canvas.raw(
            f'<rect x="{x:.1f}" y="{top}" width="{width:.1f}" height="{chip_h}" rx="{chip_h / 2}" '
            f'fill="none" stroke="{CHIP}" stroke-width="1.5" stroke-dasharray="5 6"/>'
        )
        canvas.text(item, x + chip_pad, top + chip_h / 2 + 7, size, 450, INK_2)
        x += width + chip_gap
    height = top + chip_h + PAD

    title = f"{copy.title}. {copy.next_label}: " + " ".join(copy.next_items)
    title += f" {copy.later_label}: " + ". ".join(copy.later_items) + f". {copy.dates}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {height}" '
        f'width="{WIDTH}" height="{height}" role="img" lang="{copy.lang}">'
        f"<title>{escape(title)}</title>"
        f"<defs>{canvas.glyph_defs()}</defs>"
        f'<rect x=".5" y=".5" width="{WIDTH - 1}" height="{height - 1}" rx="20" '
        f'fill="{PLANE}" stroke="{LINE}"/>' + "".join(canvas.body) + "</svg>\n"
    )


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "site" / "img"
    faces = {450: Face(450), 600: Face(600)}
    for copy, name in ((EN, "roadmap-en.svg"), (PT, "roadmap-pt-br.svg")):
        target = out / name
        target.write_text(draw(copy, faces), encoding="utf-8")
        print(name, target.stat().st_size)


if __name__ == "__main__":
    main()
