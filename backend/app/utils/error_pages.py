"""Error responses that suit whoever asked for them.

`pages.py` rendered a `pages/404.html` that did not exist, so an unknown item id
raised TemplateNotFound and came back as a bare 500. There was also no exception
handler at all, so an unknown URL rendered `{"detail":"Not Found"}` in the
browser. Both are the same gap: nothing decided what an error should look like
for a person as opposed to for a script.
"""

from __future__ import annotations

from collections.abc import Mapping
from http import HTTPStatus

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.templates import templates

# The statuses a person can plausibly navigate into and be shown a page for.
PAGE_STATUSES = frozenset({403, 404})


def wants_html(request: Request) -> bool:
    """True for a browser navigation, false for an API or HTMX call.

    Decided on Accept rather than on the path. A plain form post lands on an
    /api/ route as often as not, and the person who submitted it is looking at
    a browser window either way; `fetch` and `curl` send `*/*` and keep their
    JSON. HTMX is excluded outright: it swaps a response into part of the page,
    so a whole error document would end up nested inside the layout it extends.
    """
    if request.headers.get("hx-request"):
        return False
    return "text/html" in request.headers.get("accept", "")


def error_response(
    request: Request,
    status_code: int,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    """An error page for a browser, JSON for everything else."""
    if status_code in PAGE_STATUSES and wants_html(request):
        # A generic reason phrase ("Not Found") tells the reader nothing the
        # page does not already say better, so only a real message is passed on.
        phrase = HTTPStatus(status_code).phrase
        message = detail if detail and detail != phrase else None
        return templates.TemplateResponse(
            request,
            f"pages/{status_code}.html",
            {"message": message},
            status_code=status_code,
            headers=headers,
        )

    return JSONResponse(
        {"detail": detail or HTTPStatus(status_code).phrase},
        status_code=status_code,
        headers=headers,
    )
