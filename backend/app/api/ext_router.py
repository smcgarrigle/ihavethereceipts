"""Endpoints for the TruePriceMemory browser extension.

Everything here is read-only and gated by a bearer token (see
``app.services.ext_tokens``). CORS is intentionally not opened for these routes:
a WebExtension with ``host_permissions`` for this server is not subject to it,
and a page that is subject to it should get nothing.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.api_token import ApiToken
from app.services import ext_matcher, ext_tokens

router = APIRouter()

EXT_RATE_LIMIT = 120
EXT_RATE_WINDOW_SECONDS = 60.0
_token_requests: dict[str, list[float]] = {}


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

    now = time.monotonic()
    key = token.token_hash
    history = [t for t in _token_requests.get(key, []) if now - t < EXT_RATE_WINDOW_SECONDS]
    if len(history) >= EXT_RATE_LIMIT:
        _token_requests[key] = history
        raise HTTPException(
            status_code=429,
            detail="Too many extension requests. Please slow down.",
            headers={"Cache-Control": "no-store"},
        )
    history.append(now)
    _token_requests[key] = history
    return token


class PingResponse(BaseModel):
    ok: bool
    app: str
    version: str


class LastPaidInfo(BaseModel):
    price: float
    unit_price: float
    basis: str
    basis_label: str
    store: str
    date: str | None


class StoreStats(BaseModel):
    store: str
    last_price: float
    last_unit_price: float
    last_date: str | None
    min_price: float
    avg_price: float
    count: int


class AllStoresStats(BaseModel):
    min_price: float
    max_price: float
    avg_price: float
    best_store: str
    best_price: float
    best_date: str | None
    total_purchases: int


class HistoryPoint(BaseModel):
    date: str | None
    store: str
    price: float
    unit_price: float
    quantity: float
    weight: float | None
    unit: str | None


class PageComparison(BaseModel):
    page_price: float | None
    page_unit_price: float | None
    comparable_past_price: float | None
    basis: str
    basis_label: str
    unit_compatible: bool
    delta_pct: float | None
    verdict: str | None


class LookupMatch(BaseModel):
    item_id: int
    name: str
    confidence: int
    matched_by: str
    unit: str | None
    basis: str
    basis_label: str
    last_paid: LastPaidInfo
    at_this_store: StoreStats | None
    all_stores: AllStoresStats
    history: list[HistoryPoint]
    comparison: PageComparison | None


class LookupResponse(BaseModel):
    query: str
    cleaned_query: str
    store: str | None
    matches: list[LookupMatch]


@router.get("/ping", response_model=PingResponse)
def ping(request: Request, _token: ApiToken = Depends(require_ext_token)) -> PingResponse:
    """Connectivity and auth check, used by the extension's "Test connection"."""
    return PingResponse(ok=True, app="TruePriceMemory", version=request.app.version)


@router.get("/lookup", response_model=LookupResponse)
def lookup(
    q: Annotated[str, Query(max_length=400)] = "",
    store: Annotated[str | None, Query(max_length=120)] = None,
    size: Annotated[str | None, Query(max_length=120)] = None,
    price: Annotated[float | None, Query(ge=0.0)] = None,
    gtin: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int, Query(ge=1, le=ext_matcher.MAX_LIMIT)] = ext_matcher.DEFAULT_LIMIT,
    _token: ApiToken = Depends(require_ext_token),
    db: Session = Depends(get_db),
) -> LookupResponse:
    """Fuzzy/GTIN lookup of a retail product title against past receipt items."""
    result = ext_matcher.lookup_items(
        db,
        q=q,
        store=store,
        size=size,
        price=price,
        gtin=gtin,
        limit=limit,
    )
    return LookupResponse(**result)
