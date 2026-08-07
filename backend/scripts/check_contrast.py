"""check_contrast.py — WCAG contrast regression check for the theme tokens.

Parses the hex values straight out of static/css/themes.css (all four theme
blocks), then verifies every meaningful pairing:

- normal text on its surfaces        >= 4.5:1  (WCAG 1.4.3 AA)
- form input borders vs input fill   >= 3.0:1  (WCAG 1.4.11 non-text)

Exits non-zero on any failure, so it can run in CI or pre-commit.

Usage:
    cd backend
    uv run python scripts/check_contrast.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
THEMES_CSS = BACKEND_DIR / "static" / "css" / "themes.css"

AA_TEXT = 4.5
UI_COMPONENT = 3.0

# (foreground token, background token, minimum ratio, what it covers)
THEME_CHECKS = [
    ("text-base", "bg-main", AA_TEXT, "body text"),
    ("text-base", "bg-card", AA_TEXT, "card text"),
    ("text-base", "bg-input", AA_TEXT, "input text"),
    ("text-muted", "bg-main", AA_TEXT, "secondary text"),
    ("text-muted", "bg-card", AA_TEXT, "labels on cards"),
    ("text-subtle", "bg-main", AA_TEXT, "placeholders / timestamps"),
    ("text-subtle", "bg-card", AA_TEXT, "de-emphasised on cards"),
    ("text-code", "bg-skeleton", AA_TEXT, "inline code / debug badges"),
    ("border-input", "bg-input", UI_COMPONENT, "input boundary"),
]

HEX_PROP = re.compile(r"--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\b")


def srgb_channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hexcolor: str) -> float:
    h = hexcolor.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * srgb_channel(r) + 0.7152 * srgb_channel(g) + 0.0722 * srgb_channel(b)


def contrast(fg: str, bg: str) -> float:
    lighter, darker = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def parse_blocks(css: str) -> dict[str, dict[str, str]]:
    """Map each selector group to its hex-valued custom properties."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    blocks: dict[str, dict[str, str]] = {}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = " ".join(match.group(1).split())
        props = dict(HEX_PROP.findall(match.group(2)))
        if props:
            blocks.setdefault(selector, {}).update(props)
    return blocks


def theme_palettes() -> dict[str, dict[str, str]]:
    blocks = parse_blocks(THEMES_CSS.read_text(encoding="utf-8"))
    palettes: dict[str, dict[str, str]] = {}
    for selector, props in blocks.items():
        name_match = re.search(r"html\.(\w+)", selector)
        if name_match:
            palettes[name_match.group(1)] = props
    return palettes


def run_checks(
    label: str, palette: dict[str, str], checks: list[tuple[str, str, float, str]]
) -> list[str]:
    failures = []
    for fg, bg, minimum, purpose in checks:
        if fg not in palette or bg not in palette:
            failures.append(f"{label}: token --{fg} or --{bg} missing")
            continue
        ratio = contrast(palette[fg], palette[bg])
        status = "ok" if ratio >= minimum else "FAIL"
        print(
            f"  {label:<10} {fg:>13} on {bg:<12} {ratio:5.2f}:1"
            f"  (min {minimum})  {status}  — {purpose}"
        )
        if ratio < minimum:
            failures.append(
                f"{label}: --{fg} ({palette[fg]}) on --{bg} ({palette[bg]})"
                f" = {ratio:.2f}:1, needs {minimum}:1"
            )
    return failures


def main() -> int:
    failures: list[str] = []

    print("App themes (static/css/themes.css):")
    for theme, palette in sorted(theme_palettes().items()):
        failures += run_checks(theme, palette, THEME_CHECKS)

    if failures:
        print(f"\n❌ {len(failures)} contrast failure(s):")
        for failure in failures:
            print(f"   {failure}")
        return 1
    print("\n✅ All contrast checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
