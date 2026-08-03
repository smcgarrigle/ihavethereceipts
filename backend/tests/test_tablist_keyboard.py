"""Guards the ARIA tablist keyboard contract (WCAG 2.1.1).

A roving tabindex (`:tabindex="tab === 'x' ? 0 : -1"`) removes every
non-active tab from the Tab order on the assumption that arrow keys take
over as the way to move between them. Ship the roving tabindex without the
arrow handlers and those tabs become unreachable by keyboard entirely —
strictly worse than plain <button>s, while the ARIA advertises a correct
tablist. That exact regression shipped in 3d371e0 on the Items page.

axe-core cannot catch this: the markup is valid, only the behavior is
missing. Hence this static check on the pairing.
"""

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

ROVING_TABINDEX_RE = re.compile(r':tabindex\s*=\s*(["\'])(?:(?!\1).)*\?\s*0\s*:\s*-1')
ARROW_HANDLER_RE = re.compile(r"@keydown\.arrow-(right|left|down|up)")


def _templates_with_tablist() -> list[Path]:
    return sorted(p for p in TEMPLATES_DIR.rglob("*.html") if 'role="tablist"' in p.read_text())


def test_at_least_one_tablist_exists():
    """Guard against the parametrized tests below silently vacuously passing."""
    assert _templates_with_tablist(), "no role=tablist found — has the markup moved?"


@pytest.mark.parametrize(
    "path", _templates_with_tablist(), ids=lambda p: str(p.relative_to(TEMPLATES_DIR))
)
def test_roving_tabindex_tablist_has_arrow_key_handlers(path):
    text = path.read_text()
    if not ROVING_TABINDEX_RE.search(text):
        pytest.skip("tabs stay in the natural Tab order; arrow keys are optional")

    assert ARROW_HANDLER_RE.search(text), (
        f"{path.name}: tabs use a roving tabindex (only the active tab is Tab-reachable) "
        "but the tablist has no @keydown.arrow-* handler, so the other tabs cannot be "
        "reached by keyboard at all. Add arrow-left/right navigation, or drop the "
        "roving tabindex so every tab stays in the natural Tab order."
    )
