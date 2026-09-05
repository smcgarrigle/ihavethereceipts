import json
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
    try:
        flags_path = BASE_DIR.parent / "data" / "feature_flags.json"
        with open(flags_path, encoding="utf-8") as f:
            result: dict[str, Any] = json.load(f)
            return result
    except (OSError, json.JSONDecodeError):
        return {}


def get_currency_symbol() -> str:
    return str(_get_flags().get("currency_symbol", "$"))


def get_currency_code() -> str:
    return str(_get_flags().get("currency_code", "USD"))


templates.env.globals["csrf_token"] = get_csrf_token
templates.env.globals["currency_symbol"] = get_currency_symbol
templates.env.globals["currency_code"] = get_currency_code
