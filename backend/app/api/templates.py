from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

# Resolve path to backend/templates
BASE_DIR = Path(__file__).resolve().parent.parent.parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# CSRF helper for templates
def get_csrf_token(request: Request) -> str:
    return str(request.session.get("csrf_token", ""))


def _get_flags() -> dict[str, Any]:
    """Read the flags through the one loader rather than a fourth path."""
    from app.api.settings_router import _load_feature_flags

    return _load_feature_flags()


def get_currency_symbol() -> str:
    return str(_get_flags().get("currency_symbol", "$"))


def get_currency_code() -> str:
    return str(_get_flags().get("currency_code", "USD"))


templates.env.globals["csrf_token"] = get_csrf_token
templates.env.globals["currency_symbol"] = get_currency_symbol
templates.env.globals["currency_code"] = get_currency_code
