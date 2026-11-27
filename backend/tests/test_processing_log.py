"""Model fallbacks during receipt processing reach the processing screen.

The fallback loops in ocr.py and category_tagger.py log each failed model and
move on to the next. processing_log keeps a short line per failure for the
receipt being processed, and GET /api/receipts/{id}/status returns them so the
processing screen can print them (test_processing_terminal_ui.py covers the
browser side).
"""

from datetime import datetime
from types import SimpleNamespace

import pytest
from google.genai.errors import ServerError

from app.models import Receipt
from app.services import category_tagger, processing_log
from app.services.category_cache import category_cache


def _busy() -> ServerError:
    return ServerError(
        503,
        {
            "error": {
                "code": 503,
                "message": "This model is currently experiencing high demand.",
                "status": "UNAVAILABLE",
            }
        },
    )


@pytest.fixture(autouse=True)
def _fresh_log(monkeypatch):
    monkeypatch.setattr(processing_log, "_lines", type(processing_log._lines)())


def test_warn_outside_a_task_is_ignored():
    processing_log.warn("nobody is listening")
    assert processing_log._lines == {}


def test_warn_goes_to_the_receipt_being_processed():
    token = processing_log.begin(7)
    try:
        processing_log.warn("first")
        processing_log.warn("second")
    finally:
        processing_log.end(token)
    processing_log.warn("after end")
    assert processing_log.warnings_for(7) == ["first", "second"]
    assert processing_log.warnings_for(8) == []


def test_clear_drops_an_earlier_run():
    token = processing_log.begin(7)
    processing_log.warn("old run")
    processing_log.clear(7)
    processing_log.warn("new run")
    processing_log.end(token)
    assert processing_log.warnings_for(7) == ["new run"]


def test_lines_and_receipts_are_capped():
    token = processing_log.begin(1)
    for i in range(processing_log.MAX_LINES + 5):
        processing_log.warn(f"line {i}")
    processing_log.end(token)
    lines = processing_log.warnings_for(1)
    assert len(lines) == processing_log.MAX_LINES
    assert lines[-1] == f"line {processing_log.MAX_LINES + 4}"

    for rid in range(2, processing_log.MAX_RECEIPTS + 3):
        token = processing_log.begin(rid)
        processing_log.warn("x")
        processing_log.end(token)
    assert len(processing_log._lines) == processing_log.MAX_RECEIPTS
    assert processing_log.warnings_for(1) == []  # oldest dropped


def test_503_line_names_model_code_and_next_model():
    token = processing_log.begin(3)
    processing_log.model_failed("gemini-3.7-flash", _busy(), "categorization", ["gemini-3.6-flash"])
    processing_log.model_failed("gemini-3.6-flash", _busy(), "categorization", [])
    processing_log.end(token)
    assert processing_log.warnings_for(3) == [
        "gemini-3.7-flash unavailable for categorization (503 UNAVAILABLE: high demand)."
        " Trying gemini-3.6-flash.",
        "gemini-3.6-flash unavailable for categorization (503 UNAVAILABLE: high demand)."
        " No models left to try.",
    ]


def test_error_without_http_code_shows_its_type():
    line = processing_log.describe_model_failure("m", ValueError("long text"), "extraction")
    assert line == "m unavailable for extraction (ValueError)."


def test_busy_categorization_model_shows_in_receipt_status(client, db, monkeypatch):
    """The real batch fallback loop: first model 503s, second answers."""
    receipt = Receipt(image_path="x.jpg", status="processing", purchase_date=datetime(2026, 1, 1))
    db.add(receipt)
    db.commit()

    calls = []

    def fake_generate(model, **_kwargs):
        calls.append(model)
        if model == "gemini-busy":
            raise _busy()
        return SimpleNamespace(text='{"zzz test apples": "Produce"}')

    monkeypatch.setattr(category_tagger, "client", object())
    monkeypatch.setattr(category_tagger, "_generate_with_retry", fake_generate)
    monkeypatch.setattr(category_cache, "get", lambda _name: None)
    monkeypatch.setattr(category_cache, "batch_set", lambda _result: None)
    monkeypatch.setattr("app.services.model_manager.pinned_gemini_model", lambda: "gemini-busy")
    monkeypatch.setattr(
        "app.services.model_manager.model_manager.get_fallback_models",
        lambda: ["gemini-busy", "gemini-ok"],
    )

    token = processing_log.begin(receipt.id)
    try:
        result = category_tagger.categorize_items_batch(["zzz test apples"])
    finally:
        processing_log.end(token)

    assert calls == ["gemini-busy", "gemini-ok"]
    assert result == {"zzz test apples": "Produce"}
    body = client.get(f"/api/receipts/{receipt.id}/status").json()
    assert body["warnings"] == [
        "gemini-busy unavailable for categorization (503 UNAVAILABLE: high demand)."
        " Trying gemini-ok."
    ]


def test_status_has_empty_warnings_without_failures(client, db):
    receipt = Receipt(image_path="x.jpg", status="processing", purchase_date=datetime(2026, 1, 1))
    db.add(receipt)
    db.commit()
    assert client.get(f"/api/receipts/{receipt.id}/status").json()["warnings"] == []


def test_busy_extraction_model_is_logged(monkeypatch):
    """The real OCR fallback loop (text-paste variant): first model 503s."""
    from app.services import ocr

    def fake_generate(model, *_args):
        if model == "gemini-busy":
            raise _busy()
        return SimpleNamespace(text='{"store_name": "X", "items": []}')

    monkeypatch.setattr(ocr, "_init_gemini", lambda: None)
    monkeypatch.setattr(ocr, "_gemini_client", object())
    monkeypatch.setattr(ocr, "_gemini_model", "gemini-busy")
    monkeypatch.setattr(ocr, "_fallback_models", ["gemini-ok"])
    monkeypatch.setattr(ocr, "_make_gemini_generate", fake_generate)

    token = processing_log.begin(11)
    try:
        result = ocr._process_text_gemini("MILK 2.99")
    finally:
        processing_log.end(token)

    assert result["ocr_model"] == "gemini-ok"
    assert processing_log.warnings_for(11) == [
        "gemini-busy unavailable for extraction (503 UNAVAILABLE: high demand). Trying gemini-ok."
    ]
