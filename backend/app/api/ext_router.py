"""Endpoints for the TruePriceMemory browser extension.

Everything here is read-only and gated by a bearer token (see
``app.services.ext_tokens``). CORS is intentionally not opened for these routes:
a WebExtension with ``host_permissions`` for this server is not subject to it,
and a page that is subject to it should get nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.api_token import ApiToken
from app.services import ext_tokens

router = APIRouter()


def require_ext_token(
    response: Response,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
) -> ApiToken:
    """Dependency: 401 unless the request carries a live extension token.

    One response for every failure (missing, malformed, unknown, revoked) so a
    caller learns nothing about which it was. Replies are marked ``no-store``
    because they describe a private purchase history.
    """
    response.headers["Cache-Control"] = "no-store"
    scheme, _, credentials = (authorization or "").partition(" ")
    token = ext_tokens.verify_token(db, credentials.strip()) if scheme.lower() == "bearer" else None
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing token.",
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
    return token


class PingResponse(BaseModel):
    ok: bool
    app: str
    version: str


@router.get("/ping", response_model=PingResponse)
def ping(request: Request, _token: ApiToken = Depends(require_ext_token)) -> PingResponse:
    """Connectivity and auth check, used by the extension's "Test connection"."""
    return PingResponse(ok=True, app="TruePriceMemory", version=request.app.version)
