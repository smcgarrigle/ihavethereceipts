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
# A label baked into the tag itself. `:aria-label` is the Alpine-bound form.
STATIC_LABEL_RE = re.compile(r"\s:?aria-label\s*=|\s:?aria-labelledby\s*=")
# A label assigned at runtime, for charts whose text depends on fetched data
# (a store name, a rotating category) and so cannot be known at render time.
SET_ATTRIBUTE_RE = re.compile(r"""\.setAttribute\(\s*['"]aria-label['"]""")


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

    # Check each canvas tag individually rather than counting aria-label occurrences
    # file-wide — a file-wide count is satisfied by an aria-label on some unrelated
    # button, so it would pass with a genuinely unlabeled chart.
    needs_runtime_label = [c for c in canvases if not STATIC_LABEL_RE.search(c)]

    # Those remaining must be labeled in JS. Binding a specific setAttribute call to a
    # specific canvas would mean parsing the JS, so require at least as many calls as
    # there are unlabeled canvases — loose, but it cannot be satisfied by markup that
    # merely labels something else.
    set_attribute_calls = len(SET_ATTRIBUTE_RE.findall(text))
    assert set_attribute_calls >= len(needs_runtime_label), (
        f"{path.name}: {len(needs_runtime_label)} canvas element(s) carry no "
        f"aria-label/aria-labelledby in the tag, but only {set_attribute_calls} "
        "setAttribute('aria-label') call(s) exist to label them at runtime. "
        f"Unlabeled: {needs_runtime_label}"
    )
