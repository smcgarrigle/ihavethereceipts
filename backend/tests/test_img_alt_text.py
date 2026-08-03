"""Guards that every <img> in the app has an alt attribute (WCAG 1.1.1).

Static scan over the template sources — the app has very few real <img>
elements (icons are almost entirely emoji or inline SVG), so this is a
small, exhaustive check rather than a judgment-call heuristic.
"""

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
IMG_TAG_RE = re.compile(r"<img\b[^>]*>")


def _template_files() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: str(p.relative_to(TEMPLATES_DIR)))
def test_every_img_has_alt(path):
    text = path.read_text()
    images = IMG_TAG_RE.findall(text)
    if not images:
        pytest.skip("no <img> elements in this template")

    unlabeled = [img for img in images if "alt=" not in img and ":alt=" not in img]
    assert not unlabeled, f"{path.name}: <img> element(s) missing alt: {unlabeled}"
