"""The dashboard's OCR hint offers a hosted model; it must not demand one.

Local vision models are a supported backend (OCR_BACKEND=local), so a user
running one is already fully set up. The hint should say so, stay dismissible,
and stay dismissed.
"""

from __future__ import annotations

import json

import pytest

from app.api import settings_router


@pytest.fixture
def flags_file(tmp_path, monkeypatch):
    """Point the feature-flag store at a temp file, never the real one."""
    path = tmp_path / "feature_flags.json"
    path.write_text("{}")
    monkeypatch.setattr(settings_router, "FEATURE_FLAGS_PATH", path)
    return path


@pytest.fixture
def no_cloud_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OCR_BACKEND", "local")


@pytest.mark.usefixtures("flags_file", "no_cloud_key")
def test_hint_presents_local_as_working_not_missing(client):
    body = client.get("/").text
    assert "Image OCR is running on a local model" in body
    # The old copy framed a cloud key as a requirement.
    assert "Gemini API Key Required" not in body
    assert "Required for Image OCR" not in body


@pytest.mark.usefixtures("no_cloud_key")
def test_hint_is_hidden_once_dismissed(client, flags_file):
    assert "Image OCR is running on a local model" in client.get("/").text

    resp = client.post("/settings/flags/ocr-hint?dismissed=true")
    assert resp.status_code == 200
    assert resp.json()["ocr_hint_dismissed"] is True
    assert json.loads(flags_file.read_text())["ocr_hint_dismissed"] is True

    # Survives a fresh render, not just the click.
    assert "Image OCR is running on a local model" not in client.get("/").text


@pytest.mark.usefixtures("flags_file")
def test_hint_absent_when_a_cloud_key_is_configured(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert "Image OCR is running on a local model" not in client.get("/").text
