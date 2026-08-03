"""Guards form-field and icon-button accessible-name coverage (WCAG 4.1.2).

Static scan over the template sources (no browser needed) — the same
approach as test_chart_a11y_labels.py. Covers both a static attribute (a
name baked in at render time) and an Alpine `:`-bound equivalent (a name
computed at runtime, e.g. from a loop item or fetched data).
"""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

SKIP_INPUT_TYPES = {"hidden", "submit", "button"}


def _template_files() -> list[Path]:
    return sorted(TEMPLATES_DIR.rglob("*.html"))


def _field_id(tag) -> str | None:
    field_id = tag.get("id") or tag.get(":id")
    return field_id if isinstance(field_id, str) else None


def _field_has_accessible_name(tag, labels_for: set[str]) -> bool:
    if tag.get("aria-label") or tag.get(":aria-label"):
        return True
    if tag.get("aria-labelledby") or tag.get(":aria-labelledby"):
        return True
    if tag.get("title") or tag.get(":title"):
        return True
    if tag.get("placeholder"):
        return True
    field_id = _field_id(tag)
    if field_id and field_id in labels_for:
        return True
    parent = tag.parent
    while parent is not None:
        if getattr(parent, "name", None) == "label":
            return True
        parent = parent.parent
    return False


def _button_has_accessible_name(tag) -> bool:
    if tag.get("aria-label") or tag.get(":aria-label"):
        return True
    if tag.get("aria-labelledby") or tag.get(":aria-labelledby"):
        return True
    if tag.get("title") or tag.get(":title"):
        return True
    # dynamic text, either on the button itself or a descendant (e.g. a <span x-text="...">)
    if tag.get("x-text"):
        return True
    if tag.find(attrs={"x-text": True}):
        return True
    # types=None: Alpine repurposes <template> for x-for/x-if and clones its
    # content into the live DOM at runtime, so text inside one counts here
    # even though BeautifulSoup treats <template> content as inert by default
    # and would otherwise exclude it (bs4.element.TemplateString) from get_text().
    return bool(tag.get_text(strip=True, types=None))


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: str(p.relative_to(TEMPLATES_DIR)))
def test_form_fields_have_accessible_names(path):
    soup = BeautifulSoup(path.read_text(), "html.parser")

    labels_for = set()
    for label in soup.find_all("label"):
        f = label.get("for") or label.get(":for")
        if f:
            labels_for.add(f)

    fields = [
        f
        for f in soup.find_all(["input", "select", "textarea"])
        if (f.get("type") or "").lower() not in SKIP_INPUT_TYPES
    ]
    if not fields:
        pytest.skip("no labelable form fields in this template")

    unlabeled = [f for f in fields if not _field_has_accessible_name(f, labels_for)]
    assert not unlabeled, (
        f"{path.name}: form field(s) with no accessible name (no <label>, "
        f"aria-label, aria-labelledby, or placeholder): {unlabeled}"
    )


@pytest.mark.parametrize("path", _template_files(), ids=lambda p: str(p.relative_to(TEMPLATES_DIR)))
def test_buttons_have_accessible_names(path):
    soup = BeautifulSoup(path.read_text(), "html.parser")
    buttons = soup.find_all("button")
    if not buttons:
        pytest.skip("no <button> elements in this template")

    unlabeled = [b for b in buttons if not _button_has_accessible_name(b)]
    assert not unlabeled, (
        f"{path.name}: icon-only button(s) with no accessible name (no visible "
        f"text, aria-label, or title): {[str(b)[:120] for b in unlabeled]}"
    )
