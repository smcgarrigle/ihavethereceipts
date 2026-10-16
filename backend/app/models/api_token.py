from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiToken(Base):
    """A bearer token for the TruePriceMemory browser extension.

    Only the SHA-256 of the secret is stored, so a copy of the database cannot be
    replayed against the API. The secret is high-entropy random data rather than a
    password, which is why a fast unsalted hash is the right tool here.
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    # First few characters of the secret, shown in the UI to tell tokens apart.
    token_prefix: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
