"""Which Gemini model OCR uses, and what the app says it uses.

- Ranking used to score every name on Google's list, so special-purpose models
  (``gemini-3.8-flash-tts``, ``-live``, ``-image``, embeddings) landed in the
  fallback chain.
- Receipts and the settings page reported ``GEMINI_MODEL_NAME`` with stale
  hardcoded defaults (``gemini-1.5-flash``, ``gemini-flash``) instead of the
  model the app actually picks when it is unset.
- start_server.sh wrote ``OCR_MODEL=gemini-2.0-flash`` for the Gemini backend,
  which reads ``GEMINI_MODEL_NAME`` and never ``OCR_MODEL``.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import ocr
from app.services.model_manager import (
    ModelManager,
    is_ocr_model,
    model_manager,
    pinned_gemini_model,
)

# Google's list as cached on 2026-11-15 (data/known_models.json), in API order.
GOOGLE_LIST = [
    "gemini-3.8-flash",
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.8-live",
    "gemini-3.8-live-extended-thinking",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-image-preview",
    "gemini-3.1-flash-image",
    "gemini-3.1-flash-lite-image",
    "gemini-3.1-flash-tts-preview",
    "gemini-3.1-flash-live-preview",
    "gemini-3.5-transcribe",
    "gemini-3.5-transcribe-live",
    "gemini-3.5-live-translate-preview",
    "gemini-2.5-flash-native-audio-latest",
    "gemini-3.1-pro-preview",
    "gemini-3.1-pro-preview-customtools",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash-image",
    "gemini-2.5-flash-native-audio-preview-09-2025",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.5-pro",
    "gemini-2.5-pro-preview-tts",
    "gemini-2.5-computer-use-preview-10-2025",
    "gemini-nano-banana-2.1",
    "gemini-omni-1.2-flash",
    "gemini-omni-1.1-flash",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview",
    "gemini-omni-flash-preview",
    "gemini-pro-latest",
    "gemini-3-pro-image-preview",
    "gemini-3-pro-image",
    "gemini-4-argon",
    "gemini-4-carbon",
    "gemini-4-hydrogen",
    "gemini-robotics-er-2-preview",
    "gemini-embedding-001",
    "gemini-embedding-2-preview",
    "gemini-embedding-2",
    "gemini-robotics-er-2-streaming-preview",
    "gemini-decision-1",
]

EXPECTED_RANKING = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-pro-latest",
]


@pytest.fixture
def model_cache(tmp_path, monkeypatch):
    """Point the model cache at a temp file; returns a writer for its contents."""
    path = tmp_path / "known_models.json"
    monkeypatch.setattr(ModelManager, "CACHE_FILE", path)
    monkeypatch.setattr(ocr, "_gemini_model", None)
    monkeypatch.delenv("GEMINI_MODEL_NAME", raising=False)

    def write(models: list[str], best_model: str | None = None) -> None:
        path.write_text(
            json.dumps(
                {
                    "last_updated": "2026-11-15T00:00:00",
                    "models": models,
                    "best_model": best_model or (models[0] if models else None),
                }
            )
        )

    return write


# ── Ranking ────────────────────────────────────────────────────────────────


def test_ranking_keeps_only_general_models_newest_flash_first():
    assert model_manager.rank_models(GOOGLE_LIST) == EXPECTED_RANKING


@pytest.mark.parametrize(
    "name",
    [
        "gemini-3.8-flash-tts",
        "gemini-3.8-live",
        "gemini-3.1-flash-image",
        "gemini-3.5-transcribe",
        "gemini-2.5-flash-native-audio-latest",
        "gemini-3.1-pro-preview-customtools",
        "gemini-embedding-2",
        "gemini-4-argon",
    ],
)
def test_special_purpose_models_are_not_ocr_models(name):
    assert not is_ocr_model(name)


def test_a_cache_written_before_the_filter_cannot_pick_a_tts_model(model_cache):
    # Old caches stored the unfiltered ranking and its best_model; the cache
    # lives a week, so it has to be filtered on read too.
    model_cache(["gemini-3.8-flash-tts", "gemini-3.8-flash", "gemini-3.8-live", "gemini-3.7-flash"])

    assert model_manager.get_best_model() == "gemini-3.8-flash"
    assert model_manager.get_fallback_models() == ["gemini-3.7-flash"]


# ── GEMINI_MODEL_NAME ──────────────────────────────────────────────────────


@pytest.mark.parametrize("value", [None, "", "  ", "auto", "AUTO"])
def test_unset_empty_or_auto_means_pick_automatically(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("GEMINI_MODEL_NAME", raising=False)
    else:
        monkeypatch.setenv("GEMINI_MODEL_NAME", value)
    assert pinned_gemini_model() is None


def test_a_named_model_is_pinned(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")
    assert pinned_gemini_model() == "gemini-3.1-flash-lite"


# ── What the app reports ───────────────────────────────────────────────────


def test_label_names_the_automatic_pick(model_cache):
    model_cache(GOOGLE_LIST)
    assert ocr.gemini_model_label() == "gemini-3.8-flash (auto)"


@pytest.mark.usefixtures("model_cache")
def test_label_without_a_cache_says_auto():
    assert ocr.gemini_model_label() == "auto (picked on first receipt)"


def test_label_prefers_a_pinned_model(model_cache, monkeypatch):
    model_cache(GOOGLE_LIST)
    monkeypatch.setenv("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite")
    assert ocr.gemini_model_label() == "gemini-3.1-flash-lite"


def test_label_prefers_the_model_the_client_was_built_with(model_cache, monkeypatch):
    model_cache(GOOGLE_LIST)
    monkeypatch.setattr(ocr, "_gemini_model", "gemini-3.7-flash")
    assert ocr.gemini_model_label() == "gemini-3.7-flash"


def test_settings_page_shows_the_automatic_pick(client, model_cache, monkeypatch):
    model_cache(GOOGLE_LIST)
    monkeypatch.setenv("OCR_BACKEND", "gemini")

    page = client.get("/settings")

    assert page.status_code == 200
    assert "gemini-3.8-flash (auto)" in page.text
    assert "gemini-flash<" not in page.text  # the old hardcoded default


# ── start_server.sh ────────────────────────────────────────────────────────

SCRIPT = Path(__file__).resolve().parent.parent / "start_server.sh"


@pytest.fixture
def run_script(tmp_path):
    """Run start_server.sh against a throwaway .env, with uvicorn stubbed out."""
    if shutil.which("bash") is None:
        pytest.skip("bash not available")
    backend = tmp_path / "backend"
    (backend / ".venv" / "bin").mkdir(parents=True)
    shutil.copy(SCRIPT, backend / "start_server.sh")
    stub = backend / ".venv" / "bin" / "python"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    env_file = tmp_path / ".env"

    def run(env_text: str, keystrokes: str) -> tuple[str, str]:
        env_file.write_text(env_text)
        result = subprocess.run(
            ["bash", str(backend / "start_server.sh")],
            input=keystrokes,
            capture_output=True,
            text=True,
            timeout=30,
            env={k: v for k, v in os.environ.items() if k != "HOST"},
        )
        return result.stdout, env_file.read_text()

    return run


OLD_ENV = "OCR_BACKEND=local\nOCR_MODEL=gemini-2.0-flash\nGEMINI_API_KEY=x\n"


def test_script_gemini_defaults_to_auto_and_drops_the_stale_ocr_model(run_script):
    out, env = run_script(OLD_ENV, "3\n\n")

    assert "GEMINI_MODEL_NAME=auto" in env.splitlines()
    assert "OCR_MODEL=gemini-2.0-flash" not in env
    assert "gemini (auto" in out


def test_script_gemini_pins_a_typed_model(run_script):
    out, env = run_script(OLD_ENV, "3\ngemini-3.1-flash-lite\n")

    assert "GEMINI_MODEL_NAME=gemini-3.1-flash-lite" in env.splitlines()
    assert "gemini (gemini-3.1-flash-lite)" in out


def test_script_gemini_keeps_a_local_model_on_file(run_script):
    _, env = run_script("OCR_BACKEND=local\nOCR_MODEL=llava:7b\n", "3\n\n")

    assert "OCR_MODEL=llava:7b" in env.splitlines()
