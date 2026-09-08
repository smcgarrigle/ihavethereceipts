"""Audit finding 22: dead configuration, and runtime state tracked in git.

`Settings.FEATURES` and `is_enabled()` had zero callers anywhere, while
`.env.example` documented four `ENABLE_*` variables as live — so setting
`ENABLE_BULK_AUTO_PROCESS=false` did nothing and said nothing.

Three paths were CWD-relative (`Path("data/...")`) while everything else
resolved absolutely. Both `make run` and `start_server.sh` run from `backend/`,
so the OCR usage counter, the OCR cache and the model cache resolved into a
second `backend/data/` directory — `known_models.json` exists in both on this
machine.

And `data/feature_flags.json` / `data/ocr_filters.json` were tracked in git
despite `.gitignore` already listing `data/*.json`, so toggling any setting
dirtied the working tree.
"""

from __future__ import annotations

import ast
import pathlib
import subprocess

import pytest

from app.core.config import settings

BACKEND = pathlib.Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent


class TestTheDeadFlagsAreGone:
    def test_features_dict_is_gone(self):
        assert not hasattr(settings, "FEATURES")

    def test_is_enabled_is_gone(self):
        assert not hasattr(settings, "is_enabled")

    @pytest.mark.parametrize(
        "variable",
        [
            "ENABLE_OPEN_PRODUCE",
            "ENABLE_INGREDIENT_ANALYTICS",
            "ENABLE_BULK_AUTO_PROCESS",
            "ENABLE_EXPERIMENTAL_OCR",
        ],
    )
    def test_env_example_no_longer_advertises_them(self, variable):
        """Documenting a switch that does nothing is worse than no switch."""
        assert variable not in (ROOT / ".env.example").read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "variable",
        ["ENABLE_OPEN_PRODUCE", "ENABLE_BULK_AUTO_PROCESS", "ENABLE_EXPERIMENTAL_OCR"],
    )
    def test_nothing_reads_them(self, variable):
        """config.py is exempt: that is where the note about the deletion lives."""
        for path in (BACKEND / "app").rglob("*.py"):
            if path.name == "config.py":
                continue
            assert variable not in path.read_text(encoding="utf-8")


class TestEveryDataPathIsAbsolute:
    def test_no_module_builds_a_cwd_relative_data_path(self):
        """`Path("data/...")` depends on where the app was started from."""
        offenders: list[str] = []
        for path in (BACKEND / "app").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name != "Path" or not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    if first.value.startswith("data/"):
                        rel = path.relative_to(BACKEND)
                        offenders.append(f"{rel}:{node.lineno} Path({first.value!r})")
        assert not offenders, "CWD-relative data paths:\n  " + "\n  ".join(offenders)

    @pytest.mark.parametrize(
        "attribute",
        [
            "DATA_DIR",
            "UPLOADS_DIR",
            "FEATURE_FLAGS_PATH",
            "OCR_FILTERS_PATH",
            "OCR_USAGE_PATH",
            "OCR_CACHE_DIR",
            "KNOWN_MODELS_PATH",
        ],
    )
    def test_settings_paths_are_absolute_and_under_the_root(self, attribute):
        path = getattr(settings, attribute)
        assert path.is_absolute(), f"{attribute} is relative"
        assert path.is_relative_to(ROOT / "data"), f"{attribute} escapes data/"

    def test_the_ocr_modules_use_them(self):
        from app.services import model_manager, ocr

        assert ocr.USAGE_TRACKER_FILE == settings.OCR_USAGE_PATH
        assert ocr.CACHE_DIR == settings.OCR_CACHE_DIR
        assert model_manager.ModelManager.CACHE_FILE == settings.KNOWN_MODELS_PATH


class TestRuntimeStateIsNotTracked:
    @pytest.mark.parametrize("state", ["data/feature_flags.json", "data/ocr_filters.json"])
    def test_git_does_not_track_it(self, state):
        """.gitignore already listed data/*.json; the index disagreed."""
        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", state],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert tracked.returncode != 0, f"{state} is still tracked, so editing it dirties the tree"


class TestTheFiltersSurviveAFreshClone:
    """Untracking ocr_filters.json must not lose the curated defaults."""

    def test_the_parser_and_the_settings_page_agree(self, monkeypatch):
        from app.api import settings_router
        from app.services.pdf_parser import FALLBACK_JUNK, FALLBACK_SKIP

        monkeypatch.setattr(
            settings_router, "OCR_FILTERS_PATH", ROOT / "data" / "does-not-exist.json"
        )
        loaded = settings_router._load_ocr_filters()

        assert loaded["skip_keywords"] == list(FALLBACK_SKIP)
        assert loaded["junk_filters"] == list(FALLBACK_JUNK)
        assert loaded["skip_keywords"], "a fresh install would show no filters at all"


class TestOneFeatureFlagsPath:
    def test_every_reader_goes_through_the_one_loader(self):
        """There were four derivations; the test fixture only patched one."""
        derivations: list[str] = []
        for path in (BACKEND / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "feature_flags.json" in text and path.name != "config.py":
                derivations.append(str(path.relative_to(BACKEND)))
        assert not derivations, "feature_flags.json path built outside config: " + ", ".join(
            derivations
        )
