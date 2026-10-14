"""Test that settings pages are recognized as pages and do not collide with subpaths in the static demo builder."""

import importlib.util
import tempfile
from pathlib import Path

BUILDER = Path(__file__).resolve().parent.parent / "scripts" / "build_static_demo.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_static_demo", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_pages_are_recognized_as_pages():
    builder = _load_builder()
    assert builder.is_page("/settings") is True
    assert builder.is_page("/settings/nutrition-review") is True
    assert builder.is_page("/settings/corrections") is True
    assert builder.is_page("/api/items") is False


def test_settings_nutrition_review_and_count_coexist():
    builder = _load_builder()
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir)

        page_dest = builder.output_path(
            out, "/settings/nutrition-review", "text/html; charset=utf-8"
        )
        count_dest = builder.output_path(
            out, "/settings/nutrition-review/count", "application/json"
        )

        assert page_dest == out / "settings" / "nutrition-review" / "index.html"
        assert count_dest == out / "settings" / "nutrition-review" / "count"

        # Verify they can both be created without IsADirectoryError or FileExistsError regardless of order
        page_dest.parent.mkdir(parents=True, exist_ok=True)
        page_dest.write_text("<html><body>nutrition review</body></html>", encoding="utf-8")

        count_dest.parent.mkdir(parents=True, exist_ok=True)
        count_dest.write_text('{"count": 5}', encoding="utf-8")

        assert page_dest.is_file()
        assert count_dest.is_file()
