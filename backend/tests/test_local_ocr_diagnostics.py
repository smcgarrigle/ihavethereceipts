"""Audit finding 15: the shipped default OCR backend said nothing useful.

With `OCR_BACKEND=local` and nothing on the Ollama port — the zero-config
state — uploading a receipt produced the single phrase "Connection error.":
no URL, no mention of what should be listening on it, no way forward. Nine
lines away, `_openrouter_error_message` explains a 402 and links to the
credits page. The niche backend had the diagnostics; the recommended default
had none.

Two smaller halves of the same finding: `.env.example` ships
`GEMINI_API_KEY=your_api_key_here`, which is truthy, so the guard passed and
the first upload went to Google with a placeholder; and the Gemini
`files.upload` call sat outside any try, so a failure there escaped the
backend instead of coming back as a result.
"""

from __future__ import annotations

import httpx
import openai
import pytest

from app.services import ocr
from app.utils.api_keys import configured_key, is_placeholder

URL = "http://localhost:11434/v1"


def _dead_client(exc: Exception):
    class Dead:
        class models:
            @staticmethod
            def list():
                raise exc

        class chat:
            class completions:
                @staticmethod
                def create(**_kwargs):
                    raise exc

    return Dead()


@pytest.fixture
def local_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("OCR_BACKEND", "local")
    monkeypatch.setenv("OCR_BACKEND_URL", URL)
    img = tmp_path / "receipt.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)
    return str(img)


class TestPlaceholderKeys:
    @pytest.mark.parametrize(
        "value",
        [
            "your_api_key_here",  # the literal .env.example value
            "your_key_here",
            "YOUR-GEMINI-KEY-HERE",
            "changeme",
            "",
            "   ",
            None,
        ],
    )
    def test_recognised(self, value):
        assert is_placeholder(value) is True

    @pytest.mark.parametrize("value", ["AIzaSyRealLookingKey123", "sk-or-v1-abc", "x" * 39])
    def test_real_keys_pass(self, value):
        assert is_placeholder(value) is False

    def test_configured_key_hides_placeholders(self, monkeypatch):
        monkeypatch.setenv("SOME_KEY", "your_api_key_here")
        assert configured_key("SOME_KEY") is None
        monkeypatch.setenv("SOME_KEY", "a-real-one")
        assert configured_key("SOME_KEY") == "a-real-one"

    def test_gemini_init_refuses_the_example_value(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "your_api_key_here")
        monkeypatch.setattr(ocr, "_gemini_client", None)
        with pytest.raises(ValueError) as exc:
            ocr._init_gemini()
        assert "placeholder" in str(exc.value)
        assert "aistudio.google.com" in str(exc.value), "no way forward offered"

    def test_the_dashboard_does_not_claim_a_placeholder_is_a_key(self, client, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "your_api_key_here")
        assert client.get("/").status_code == 200
        assert configured_key("GEMINI_API_KEY") is None


class TestTheLocalBackendExplainsItself:
    def test_nothing_listening_names_the_url_and_the_servers(self, local_backend, monkeypatch):
        monkeypatch.setattr(
            ocr, "_get_local_client", lambda: _dead_client(openai.APIConnectionError(request=None))
        )
        error = ocr._process_local([local_backend])["error"]

        assert error != "Connection error.", "still the bare SDK string"
        assert URL in error, "the configured URL is not named"
        assert "Ollama" in error and "LM Studio" in error, "neither server is named"
        assert "OCR_BACKEND=gemini" in error, "no hosted alternative offered"

    def test_a_timeout_reads_differently_from_a_refusal(self, local_backend, monkeypatch):
        monkeypatch.setattr(
            ocr, "_get_local_client", lambda: _dead_client(openai.APITimeoutError(request=None))
        )
        error = ocr._process_local([local_backend])["error"]

        # A timeout with no __cause__ cannot be attributed to connecting, so it
        # reads as the model being slow — and now names the budget it exceeded.
        assert "did not finish" in error
        assert "Nothing answered" not in error, "a timeout was reported as a refusal"
        assert URL in error

    def test_a_missing_model_says_so(self, local_backend, monkeypatch):
        # NotFoundError needs a real response to read its request off.
        request = httpx.Request("POST", URL)
        not_found = openai.NotFoundError(
            "no model", response=httpx.Response(404, request=request), body=None
        )
        monkeypatch.setattr(ocr, "_get_local_client", lambda: _dead_client(not_found))
        error = ocr._process_local([local_backend])["error"]

        assert "no such model loaded" in error
        assert URL in error

    def test_an_unrecognised_failure_still_names_the_url(self, local_backend, monkeypatch):
        monkeypatch.setattr(ocr, "_get_local_client", lambda: _dead_client(RuntimeError("kaboom")))
        error = ocr._process_local([local_backend])["error"]

        assert URL in error
        assert "kaboom" in error, "the underlying reason was swallowed"


class TestGeminiUploadFailureIsAResult:
    def test_it_does_not_escape_the_backend(self, monkeypatch, tmp_path):
        img = tmp_path / "receipt.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 128)

        class Client:
            class files:
                @staticmethod
                def upload(**_kwargs):
                    raise RuntimeError("API key not valid")

        monkeypatch.setattr(ocr, "_gemini_client", Client())
        monkeypatch.setattr(ocr, "_gemini_model", "gemini-flash")
        monkeypatch.setattr(ocr, "_init_gemini", lambda: None)

        result = ocr._process_gemini([str(img)])
        assert "error" in result, "the exception propagated instead of returning a result"
        assert "API key not valid" in result["error"]


class TestTheTimeoutBudgets:
    """A flat 30-minute timeout covered connecting as well as reading.

    An OCR_BACKEND_URL pointing at a host that drops packets rather than
    refusing them — a firewalled box, a stale Tailscale address, a container
    that has gone — hung an upload for that budget times the SDK's retries,
    which is up to 90 minutes, instead of failing fast with the message above.
    Measured against 127.0.0.1:1, which drops on this machine: 11 seconds.
    """

    def test_connecting_is_capped_short(self):
        from app.services import ocr

        ocr._local_client = None
        client = ocr._get_local_client()
        assert client.timeout.connect == 5.0

    def test_reading_gets_the_configured_budget(self, monkeypatch):
        from app.services import ocr

        monkeypatch.setenv("OCR_TIMEOUT_SECONDS", "240")
        ocr._local_client = None
        try:
            assert ocr._get_local_client().timeout.read == 240.0
        finally:
            ocr._local_client = None

    def test_the_default_read_budget_is_three_minutes(self, monkeypatch):
        from app.services import ocr

        monkeypatch.delenv("OCR_TIMEOUT_SECONDS", raising=False)
        assert ocr._local_read_timeout() == 180.0

    @pytest.mark.parametrize("bad", ["", "   ", "not-a-number", "0", "-30"])
    def test_a_nonsense_setting_falls_back_to_the_default(self, bad, monkeypatch):
        from app.services import ocr

        monkeypatch.setenv("OCR_TIMEOUT_SECONDS", bad)
        assert ocr._local_read_timeout() == ocr.DEFAULT_LOCAL_READ_TIMEOUT

    def test_retries_do_not_multiply_the_ceiling(self):
        """3 minutes must mean 3 minutes, not 3 attempts of 3 minutes."""
        from app.services import ocr

        ocr._local_client = None
        assert ocr._get_local_client().max_retries == 0

    def test_a_connect_timeout_is_not_reported_as_a_slow_model(self, local_backend, monkeypatch):
        """Both are APITimeoutError; only __cause__ tells them apart."""
        request = httpx.Request("POST", URL)
        timed_out = openai.APITimeoutError(request=request)
        timed_out.__cause__ = httpx.ConnectTimeout("too slow", request=request)

        monkeypatch.setattr(ocr, "_get_local_client", lambda: _dead_client(timed_out))
        error = ocr._process_local([local_backend])["error"]

        assert "Nothing answered" in error
        assert "did not finish" not in error, "a dead address blamed the model"
        assert "OCR_BACKEND_URL" in error

    def test_a_real_read_timeout_still_blames_the_model(self, local_backend, monkeypatch):
        request = httpx.Request("POST", URL)
        timed_out = openai.APITimeoutError(request=request)
        timed_out.__cause__ = httpx.ReadTimeout("too slow", request=request)

        monkeypatch.setattr(ocr, "_get_local_client", lambda: _dead_client(timed_out))
        error = ocr._process_local([local_backend])["error"]

        assert "did not finish" in error
        assert "OCR_TIMEOUT_SECONDS" in error, "no way to raise the limit offered"
