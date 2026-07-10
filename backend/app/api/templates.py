from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

# Resolve path to backend/templates
BASE_DIR = Path(__file__).resolve().parent.parent.parent

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# CSRF helper for templates
def get_csrf_token(request: Request) -> str:
    return request.session.get("csrf_token", "")


templates.env.globals["csrf_token"] = get_csrf_token
