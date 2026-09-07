"""What an upload is allowed to be, and how it is allowed to come back out.

The type check used to read ``file.content_type`` -- a client-supplied header --
while the stored extension came from ``Path(file.filename).suffix`` with no
allowlist at all. ``data/uploads`` is served back from the app's own origin, so
a POST declaring ``image/png`` with ``filename="x.html"`` wrote a file that came
back as ``text/html`` under the app's CSP, script and all.

So the extension is taken from the bytes rather than from anything the client
says, and serving refuses anything whose extension is not one we chose.
"""

from __future__ import annotations

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

# Longest signature first so a prefix never shadows a longer match.
_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    (b"%PDF-", ".pdf", "application/pdf"),
    (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
)

# Enough bytes for every signature above, with room to spare.
SNIFF_BYTES = 16

_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".pdf": "application/pdf",
}

ALLOWED_DESCRIPTION = "JPG, PNG, or PDF"


def sniff(head: bytes) -> tuple[str, str] | None:
    """Return (extension, media type) for content we recognise, else None.

    ``head`` only needs to be the first :data:`SNIFF_BYTES` of the file.
    """
    for signature, suffix, media_type in _SIGNATURES:
        if head.startswith(signature):
            return suffix, media_type
    return None


def media_type_for(suffix: str) -> str | None:
    """The content type a stored upload may be served with, or None to refuse.

    Returning None is the safe answer for anything already on disk that this
    module would not accept today -- there are files in ``data/uploads`` older
    than the checks above.
    """
    return _MEDIA_TYPES.get(suffix.lower())
