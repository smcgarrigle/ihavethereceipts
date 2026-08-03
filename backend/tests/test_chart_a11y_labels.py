"""Guards the "every chart has a role and a label" a11y invariant.

Static text scan over the template sources (no browser needed) — charts are
rendered client-side by Chart.js, so a live-DOM check would need Playwright,
but the accessibility contract lives entirely in the markup/JS that sets
role="img" and aria-label, which we can verify by inspection.
"""

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
CANVAS_TAG_RE = re.compile(r"<canvas\b[^>]*>")
ARIA_LABEL_RE = re.compile(r"""aria-label=["']|\.setAttribute\(\s*['"]aria-label['"]""")


def _template_files() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: str(p.relative_to(TEMPLATES_DIR)))
def test_every_chart_canvas_is_labeled(path):
    text = path.read_text()
    canvases = CANVAS_TAG_RE.findall(text)
    if not canvases:
        pytest.skip("no <canvas> elements in this template")

    unlabeled = [c for c in canvases if 'role="img"' not in c]
    assert not unlabeled, (
        f'{path.name}: canvas element(s) missing role="img" — charts must be '
        f"announced as images to screen readers, not skipped as decorative: {unlabeled}"
    )

    # aria-label may be a static attribute (labels fixed at render time) or set via
    # a JS .setAttribute call (labels that depend on fetched data, e.g. a store name).
    aria_label_count = len(ARIA_LABEL_RE.findall(text))
    assert aria_label_count >= len(canvases), (
        f"{path.name}: {len(canvases)} canvas element(s) but only {aria_label_count} "
        "aria-label assignment(s) found (static attribute or setAttribute call) — "
        "every chart needs a descriptive label."
    )
