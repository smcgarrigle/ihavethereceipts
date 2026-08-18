"""
Guards for the OpenRouter backend's two dangerous defaults.

1. Money. The local backend auto-detects its model by taking the first entry
   from client.models.list(). Against OpenRouter that call returns the entire
   public catalogue, so the same heuristic would silently discard OCR_MODEL and
   run — and bill — an arbitrary model. OpenRouter must never auto-detect, and
   must refuse a non-":free" model unless the user opted in.

2. Privacy. Receipts are personal purchase records. Every OpenRouter request
   must carry provider.data_collection=deny so the routing layer refuses
   providers that retain or train on inputs, unless explicitly overridden.
"""

import pytest

from app.services import ocr


@pytest.fixture
def openrouter_env(monkeypatch):
    monkeypatch.setenv("OCR_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENROUTER_ALLOW_PAID", raising=False)
    monkeypatch.delenv("OPENROUTER_ALLOW_TRAINING", raising=False)
    monkeypatch.delenv("OCR_MODEL", raising=False)


@pytest.mark.usefixtures("openrouter_env")
def test_default_model_is_free_and_vision_capable():
    assert ocr.OPENROUTER_DEFAULT_MODEL.endswith(":free")
    assert ocr.OPENROUTER_DEFAULT_MODEL in ocr.OPENROUTER_FREE_VISION_MODELS
    assert ocr._openrouter_model() == ocr.OPENROUTER_DEFAULT_MODEL


@pytest.mark.usefixtures("openrouter_env")
def test_empty_ocr_model_falls_back_to_default(monkeypatch):
    """
    The deprecated backend/.env ships `OCR_MODEL=` (empty). It loads before the
    root .env and, being "set", blocks it — so an empty value must be treated
    as unset rather than sent to OpenRouter as a blank model ID.
    """
    monkeypatch.setenv("OCR_MODEL", "")
    assert ocr._openrouter_model() == ocr.OPENROUTER_DEFAULT_MODEL


@pytest.mark.usefixtures("openrouter_env")
def test_paid_model_is_refused_by_default(monkeypatch):
    monkeypatch.setenv("OCR_MODEL", "anthropic/claude-opus-4")
    with pytest.raises(RuntimeError, match="not a ':free' model"):
        ocr._openrouter_model()


@pytest.mark.usefixtures("openrouter_env")
def test_paid_model_allowed_only_with_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("OCR_MODEL", "anthropic/claude-opus-4")
    monkeypatch.setenv("OPENROUTER_ALLOW_PAID", "1")
    assert ocr._openrouter_model() == "anthropic/claude-opus-4"


@pytest.mark.usefixtures("openrouter_env")
def test_missing_api_key_raises_actionable_error(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(ocr, "_openrouter_client", None)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        ocr._get_openrouter_client()


@pytest.mark.usefixtures("openrouter_env")
def test_local_backend_url_never_hijacks_openrouter(monkeypatch):
    """
    OCR_BACKEND_URL points at Ollama/LM Studio and is usually still set from a
    previous local setup. Honouring it under OCR_BACKEND=openrouter posts
    receipts to a dead localhost port and hangs until the timeout.
    """
    monkeypatch.setenv("OCR_BACKEND_URL", "http://localhost:1234/v1")
    assert ocr._local_backend_url() == ocr.OPENROUTER_URL

    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://proxy.example/api/v1")
    assert ocr._local_backend_url() == "https://proxy.example/api/v1"


@pytest.mark.usefixtures("openrouter_env")
def test_requests_deny_data_collection_by_default():
    assert ocr._openrouter_extra_body() == {"provider": {"data_collection": "deny"}}


@pytest.mark.usefixtures("openrouter_env")
def test_training_opt_in_drops_the_deny_policy(monkeypatch):
    monkeypatch.setenv("OPENROUTER_ALLOW_TRAINING", "1")
    assert ocr._openrouter_extra_body() == {}


@pytest.mark.usefixtures("openrouter_env")
def test_openrouter_never_auto_detects_model(monkeypatch):
    """
    The catalogue's first entry must not win over OCR_MODEL. Simulates
    client.models.list() returning a paid model ahead of everything else.
    """
    calls = {"list": 0}

    class _FakeModels:
        def list(self):
            calls["list"] += 1

            class _R:
                data = [type("M", (), {"id": "openai/gpt-4o"})()]

            return _R()

    class _FakeClient:
        models = _FakeModels()

        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs):
                    raise AssertionError(f"should not reach the API: {kwargs['model']}")

    monkeypatch.setattr(ocr, "_get_local_client", lambda: _FakeClient())
    monkeypatch.setenv("OCR_MODEL", "openai/gpt-4o")  # paid → guard must fire

    result = ocr._process_local(["/nonexistent.jpg"])

    assert calls["list"] == 0, "OpenRouter must not call models.list()"
    assert result.get("error")
    assert ":free" in result["error"]


@pytest.mark.usefixtures("openrouter_env")
def test_404_under_deny_explains_the_free_vs_private_tradeoff():
    """
    Measured against the live API: every free vision model 404s under
    data_collection=deny. The message must name the actual tradeoff and both
    escape hatches, not send the user hunting for a valid model name.
    """

    class _NotFound(Exception):
        status_code = 404

    msg = ocr._openrouter_error_message(_NotFound("no endpoints"), "some/model:free")
    assert "OPENROUTER_ALLOW_TRAINING=1" in msg
    assert "OCR_BACKEND=local" in msg


@pytest.mark.usefixtures("openrouter_env")
def test_error_messages_distinguish_402_from_429():
    class _Err(Exception):
        status_code = 402

    msg = ocr._openrouter_error_message(_Err("nope"), "some/model:free")
    assert "402" in msg and "balance" in msg.lower()

    class _Rate(Exception):
        status_code = 429

    rate_msg = ocr._openrouter_error_message(_Rate("slow down"), "some/model:free")
    assert "50/day" in rate_msg
