"""Audit finding 21: SBOM.md had drifted from the lock file on every package sampled.

It was maintained by hand, and 34 of its 48 Python packages were wrong —
fastapi said 0.128.0 against 0.141.1 installed, google-genai 1.60.0 against
2.17.0. A bill of materials nobody can trust is worse than none, because it
gets quoted.

Versions are now derived from backend/uv.lock by scripts/refresh_sbom.py and
this fails when they drift. Licence and purpose stay editorial: neither is in
the lock file, and the purpose column is the part of the document with any
value in it.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
SBOM = BACKEND.parent / "SBOM.md"
SCRIPT = BACKEND / "scripts" / "refresh_sbom.py"


@pytest.fixture(scope="module")
def refresher():
    spec = importlib.util.spec_from_file_location("refresh_sbom", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sbom_exists():
    assert SBOM.is_file()


def test_versions_match_the_lock_file(refresher):
    """The drift guard. Fix with: uv run python scripts/refresh_sbom.py"""
    _updated, changes = refresher.refresh(SBOM.read_text(encoding="utf-8"))
    assert not changes, (
        "SBOM.md versions have drifted from backend/uv.lock:\n  "
        + "\n  ".join(changes)
        + "\n\nRun: uv run python scripts/refresh_sbom.py"
    )


def test_the_refresher_only_touches_the_version_column(refresher):
    """It must not rewrite the editorial columns it cannot regenerate."""
    row = "| [fastapi](https://fastapi.tiangolo.com/) | 0.0.1 | MIT | ASGI web framework |\n"
    updated, changes = refresher.refresh(row)
    assert changes, "a stale version was not detected"
    assert "MIT" in updated
    assert "ASGI web framework" in updated
    assert "https://fastapi.tiangolo.com/" in updated
    assert "0.0.1" not in updated


def test_an_uninstalled_package_is_left_alone(refresher):
    """Rows for things no longer in the lock are not the version guard's business."""
    row = "| [some-removed-thing](https://example.invalid/) | 1.2.3 | MIT | gone |\n"
    updated, changes = refresher.refresh(row)
    assert changes == []
    assert updated == row
