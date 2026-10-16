"""Issue, verify and revoke the bearer tokens used by the browser extension."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.api_token import ApiToken

TOKEN_PREFIX = "tpm_"
DEFAULT_NAME = "Browser extension"
MAX_NAME_LENGTH = 60
# Revoke one before issuing another. Stops a loop or a stuck button from filling
# the table, and keeps the list a person can actually audit.
MAX_ACTIVE_TOKENS = 10
# A content script may call the API on every page view. Recording each one would
# turn every read into a SQLite write, so "last used" is only refreshed this often.
LAST_USED_RESOLUTION = timedelta(minutes=1)


def _now() -> datetime:
    """Naive UTC, matching how SQLite hands DateTime columns back."""
    return datetime.now(UTC).replace(tzinfo=None)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def clean_name(name: str | None) -> str:
    return (name or "").strip()[:MAX_NAME_LENGTH].strip() or DEFAULT_NAME


def active_tokens(db: Session) -> list[ApiToken]:
    return (
        db.query(ApiToken)
        .filter(ApiToken.revoked_at.is_(None))
        .order_by(ApiToken.created_at.desc(), ApiToken.id.desc())
        .all()
    )


def create_token(db: Session, name: str | None) -> tuple[ApiToken, str] | None:
    """Create a token. Returns ``(row, secret)``, or None when at the active cap.

    The secret exists only in the return value: it is the caller's one chance to
    show it.
    """
    if len(active_tokens(db)) >= MAX_ACTIVE_TOKENS:
        return None
    secret = TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = ApiToken(
        name=clean_name(name),
        token_hash=hash_token(secret),
        token_prefix=secret[: len(TOKEN_PREFIX) + 4],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row, secret


def revoke_token(db: Session, token_id: int) -> bool:
    row = db.get(ApiToken, token_id)
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    db.commit()
    return True


def verify_token(db: Session, raw: str | None) -> ApiToken | None:
    """The live token this secret belongs to, or None. Never says why it failed."""
    if not raw or not raw.startswith(TOKEN_PREFIX):
        return None
    digest = hash_token(raw)
    row = db.query(ApiToken).filter(ApiToken.token_hash == digest).first()
    # The lookup is by hash, so a timing difference reveals nothing about the
    # secret, but compare in constant time anyway rather than rely on that.
    if row is None or not hmac.compare_digest(row.token_hash, digest) or row.revoked_at:
        return None

    now = _now()
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_RESOLUTION:
        row.last_used_at = now
        db.commit()
    return row
