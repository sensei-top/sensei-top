"""Validate the "Table" palette: WCAG contrast plus colour-vision-
deficiency (CVD) separation. Stdlib only.

``docs/frontend.md`` (and now ``docs/design-system.md``) says the palette
"was validated with a script" — this is that script. The palette below is
declared once, at the top, because it is the thing you edit when a colour
changes; it must be kept in step by hand with ``web/src/index.css`` and
``web/src/theme.ts`` (which cannot import this Python file, and which
recharts needs as literal hex strings rather than CSS custom properties —
see the comment in both).

Method:
  - WCAG 2.x relative luminance and contrast ratio (the sRGB piecewise
    gamma curve, then the 0.2126/0.7152/0.0722 luminance weights).
  - CVD simulation: the Machado, Oliveira & Fernandes (2009) full-severity
    (1.0) linear-RGB transform matrices for protanopia, deuteranopia and
    tritanopia, applied directly to linear sRGB (no re-encoding needed,
    since the next step converts straight to CIE XYZ).
  - Separation between two colours is CIE76 ΔE in CIELAB (D65 reference
    white), computed after the CVD transform for the simulated rows.

Run: ``uv run python scripts/validate_palette.py``. Exits non-zero if any
hard-fail check fails. The win/loss ΔE-under-deuteranopia row is printed as
ADVISORY, never a hard failure — see the note at that check.
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# The palette. Mirrors web/src/index.css's custom properties and
# web/src/theme.ts's Tokens — edit all three together.
# ---------------------------------------------------------------------------

SURFACES = {
    "plane": "#0b0c14",
    "surface-1": "#131522",
    "surface-2": "#1a1d2e",
    "surface-3": "#24283d",
}

TEXT = {
    "ink": "#f2f3f8",
    "ink-2": "#b9bdd0",
    "muted": "#989db5",
}

# Opaque hairlines only — not contrast-checked, since a chart's grid/axis and
# a plain rule are decoration, not text or a data mark.
LINES = {
    "line": "#252a40",
    "line-2": "#343a57",
}

# Also used as chart series marks; assigned by entity (self/opponent/field),
# never by rank.
SERIES = {
    "series-1 (self)": "#4a95f0",
    "series-2 (opponent)": "#f0762f",
    "series-3 (field)": "#9ee0a8",
}

STATUS = {
    "win": "#57bd6d",
    "loss": "#e66e62",
    "warn": "#d9a13a",
}

MANA = {
    "mana-w": "#f0f2c0",
    "mana-u": "#b5cde3",
    "mana-b": "#aca29a",
    "mana-r": "#db8664",
    "mana-g": "#93b483",
}

MANA_GLYPH = "#111111"

# The brand accent: the primary action and the one item a page leads with,
# never a data colour. --on-accent is the only text colour allowed on an
# accent fill.
ACCENT = "#f4b6e4"
ON_ACCENT = "#1a1020"

# A tinted result pill: the status colour at this alpha, composited in sRGB
# over the surface it sits on, read as text against that composite.
PILL_TINT = 0.12
PILL_SURFACES = ("plane", "surface-1", "surface-2")

TEXT_CONTRAST_MIN = 4.5
NONTEXT_CONTRAST_MIN = 3.0
SERIES_DELTA_E_MIN = 20.0

# ---------------------------------------------------------------------------
# Colour maths
# ---------------------------------------------------------------------------


def hex_to_srgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    r, g, b = (int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))
    return r, g, b


def _srgb_channel_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb_to_linear(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(_srgb_channel_to_linear(c) for c in rgb)  # type: ignore[return-value]


def relative_luminance(hex_value: str) -> float:
    """WCAG 2.x relative luminance, 0 (black) to 1 (white)."""
    r, g, b = srgb_to_linear(hex_to_srgb(hex_value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG contrast ratio, 1.0 (no difference) to 21.0 (black on white)."""
    la, lb = relative_luminance(hex_a), relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


# Machado, Oliveira & Fernandes (2009), full severity (1.0), applied to
# linear RGB. These are the published simulation matrices, not an
# approximation of them.
CVD_MATRICES: dict[str, tuple[tuple[float, float, float], ...]] = {
    "protan": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deutan": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritan": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}

# sRGB (D65) linear-RGB -> XYZ, IEC 61966-2-1.
RGB_TO_XYZ = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)

# D65 reference white, 0-100 scale.
D65_WHITE = (95.047, 100.0, 108.883)


def _apply_matrix(
    matrix: tuple[tuple[float, float, float], ...], vec: tuple[float, float, float]
) -> tuple[float, float, float]:
    return tuple(sum(row[i] * vec[i] for i in range(3)) for row in matrix)  # type: ignore[return-value]


def simulate_cvd(hex_value: str, kind: str | None) -> tuple[float, float, float]:
    """Linear RGB after simulating CVD `kind` (None = normal vision), clamped
    to a non-negative gamut so the cube root below stays real-valued."""
    linear = srgb_to_linear(hex_to_srgb(hex_value))
    if kind is not None:
        linear = _apply_matrix(CVD_MATRICES[kind], linear)
    return tuple(max(0.0, c) for c in linear)  # type: ignore[return-value]


def linear_to_lab(linear_rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = _apply_matrix(RGB_TO_XYZ, linear_rgb)
    x, y, z = x * 100.0, y * 100.0, z * 100.0
    xn, yn, zn = D65_WHITE

    def f(t: float) -> float:
        delta = 6.0 / 29.0
        return t ** (1.0 / 3.0) if t > delta**3 else t / (3 * delta**2) + 4.0 / 29.0

    fx, fy, fz = f(x / xn), f(y / yn), f(z / zn)
    ell = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return ell, a, b


def delta_e76(lab_a: tuple[float, float, float], lab_b: tuple[float, float, float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(lab_a, lab_b, strict=True)) ** 0.5


def delta_e_under(hex_a: str, hex_b: str, kind: str | None) -> float:
    lab_a = linear_to_lab(simulate_cvd(hex_a, kind))
    lab_b = linear_to_lab(simulate_cvd(hex_b, kind))
    return delta_e76(lab_a, lab_b)


def composite_over(fg_hex: str, bg_hex: str, alpha: float) -> str:
    """A tinted pill's effective colour: `fg_hex` at `alpha` alpha, painted
    over `bg_hex`, blended in sRGB (gamma-encoded) space the way a browser's
    `background: rgb(... / alpha)` over a solid backdrop actually composites,
    not in linear light."""
    fg, bg = hex_to_srgb(fg_hex), hex_to_srgb(bg_hex)
    mixed = tuple(alpha * f + (1 - alpha) * b for f, b in zip(fg, bg, strict=True))
    return "#" + "".join(f"{round(c * 255):02x}" for c in mixed)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

hard_failed = False


def _row(label: str, value: float, threshold: float, *, minimum: bool = True) -> None:
    global hard_failed
    ok = value >= threshold if minimum else value <= threshold
    status = "PASS" if ok else "FAIL"
    if not ok:
        hard_failed = True
    print(f"{status}  {label:<52} {value:6.2f}  (threshold {threshold})")


def _advisory(label: str, value: float) -> None:
    print(f"ADVISORY  {label:<50} ΔE = {value:6.2f}  (informational only, never fails)")


def main() -> int:
    # Sanity check the maths against a known pair before trusting anything
    # else: pure black vs pure white is the textbook 21.0 contrast ratio.
    sanity = contrast_ratio("#000000", "#ffffff")
    print(f"sanity check: contrast(#000, #fff) = {sanity:.4f} (expect 21.0)")
    if abs(sanity - 21.0) > 0.01:
        print("FAIL  contrast_ratio() implementation is wrong — stopping.")
        return 1
    print()

    print("-- text contrast (ink / ink-2 / muted) >= 4.5 on every surface --")
    for text_name, text_hex in TEXT.items():
        for surface_name, surface_hex in SURFACES.items():
            _row(
                f"{text_name} on {surface_name}",
                contrast_ratio(text_hex, surface_hex),
                TEXT_CONTRAST_MIN,
            )
    print()

    print("-- non-text contrast (series / status) >= 3.0 on every surface --")
    non_text = {**SERIES, **STATUS}
    for name, hex_value in non_text.items():
        for surface_name, surface_hex in SURFACES.items():
            _row(
                f"{name} on {surface_name}",
                contrast_ratio(hex_value, surface_hex),
                NONTEXT_CONTRAST_MIN,
            )
    print()

    print("-- win / loss / warn are also used as text: >= 4.5 --")
    for name, hex_value in STATUS.items():
        for surface_name, surface_hex in SURFACES.items():
            _row(
                f"{name} (as text) on {surface_name}",
                contrast_ratio(hex_value, surface_hex),
                TEXT_CONTRAST_MIN,
            )
    print()

    print("-- mana discs vs surface-1 >= 3.0; mana-glyph vs each disc >= 4.5 --")
    for name, hex_value in MANA.items():
        contrast = contrast_ratio(hex_value, SURFACES["surface-1"])
        _row(f"{name} on surface-1", contrast, NONTEXT_CONTRAST_MIN)
    for name, hex_value in MANA.items():
        _row(f"mana-glyph on {name}", contrast_ratio(MANA_GLYPH, hex_value), TEXT_CONTRAST_MIN)
    print()

    print("-- series pairs: CIE76 ΔE >= 20 under normal vision and every CVD sim (hard fail) --")
    pairs = [
        ("series-1 (self)", "series-2 (opponent)"),
        ("series-1 (self)", "series-3 (field)"),
        ("series-2 (opponent)", "series-3 (field)"),
    ]
    for name_a, name_b in pairs:
        hex_a, hex_b = SERIES[name_a], SERIES[name_b]
        for kind in (None, "protan", "deutan", "tritan"):
            label = f"{name_a} vs {name_b} ({kind or 'normal'})"
            _row(label, delta_e_under(hex_a, hex_b, kind), SERIES_DELTA_E_MIN)
    print()

    print("-- win/loss separation under CVD: ADVISORY only (the word is always present too) --")
    for kind in (None, "protan", "deutan", "tritan"):
        label = f"win vs loss ({kind or 'normal'})"
        _advisory(label, delta_e_under(STATUS["win"], STATUS["loss"], kind))
    print()

    print("-- accent on every surface: >= 4.5 (it is used as text) --")
    for surface_name, surface_hex in SURFACES.items():
        _row(f"accent on {surface_name}", contrast_ratio(ACCENT, surface_hex), TEXT_CONTRAST_MIN)
    print()

    print("-- on-accent text on an accent fill: >= 4.5 --")
    _row("on-accent on accent", contrast_ratio(ON_ACCENT, ACCENT), TEXT_CONTRAST_MIN)
    print()

    print(
        "-- accent vs every data colour: CIE76 ΔE >= 20 under normal vision "
        "and every CVD sim (hard fail) --"
    )
    for name, hex_value in {**SERIES, **STATUS}.items():
        for kind in (None, "protan", "deutan", "tritan"):
            label = f"accent vs {name} ({kind or 'normal'})"
            _row(label, delta_e_under(ACCENT, hex_value, kind), SERIES_DELTA_E_MIN)
    print()

    print(
        "-- tinted pills: win / loss / warn on their own 12% tint, "
        "over plane, surface-1 and surface-2: >= 4.5 --"
    )
    for name, hex_value in STATUS.items():
        for surface_name in PILL_SURFACES:
            tint = composite_over(hex_value, SURFACES[surface_name], PILL_TINT)
            _row(
                f"{name} on its own tint over {surface_name}",
                contrast_ratio(hex_value, tint),
                TEXT_CONTRAST_MIN,
            )
    print()

    if hard_failed:
        print("RESULT: one or more hard-fail checks failed.")
        return 1
    print("RESULT: all hard-fail checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
