"""Audit finding 11: the stored extension came from the client's filename.

The type check read `file.content_type`, a client-supplied header, while the
extension came from `Path(file.filename).suffix` with no allowlist. Uploads are
served back from the app's own origin, so a POST declaring `image/png` with
`filename="x.html"` wrote a file that came back as `text/html` under the app's
CSP — with its script intact. Two such files were still sitting in
`data/uploads` when this was written.
"""

from __future__ import annotations

import pathlib

import pytest

from app.utils.upload_validation import media_type_for, sniff

UPLOADS = pathlib.Path(__file__).resolve().parent.parent.parent / "data" / "uploads"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"\x00" * 64
HTML = b"<script>window.__pwned=1</script>"


@pytest.fixture(autouse=True)
def _clean_uploads():
    """Delete whatever a test wrote into the real data/uploads directory.

    The upload endpoints write to the project's actual uploads directory, which
    is why 741 stand-in "fake image" files from earlier runs are sitting in it.
    """
    before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
    yield
    if UPLOADS.exists():
        for path in set(UPLOADS.iterdir()) - before:
            path.unlink(missing_ok=True)


def _new_files(before: set[pathlib.Path]) -> list[pathlib.Path]:
    return sorted(set(UPLOADS.iterdir()) - before) if UPLOADS.exists() else []


class TestSniffing:
    @pytest.mark.parametrize(
        ("head", "expected"),
        [
            (PNG, (".png", "image/png")),
            (JPG, (".jpg", "image/jpeg")),
            (PDF, (".pdf", "application/pdf")),
        ],
    )
    def test_recognised_content(self, head, expected):
        assert sniff(head) == expected

    @pytest.mark.parametrize("head", [HTML, b"GIF89a", b"", b"#!/bin/sh\n", b"\xff\xd8"])
    def test_everything_else_is_refused(self, head):
        assert sniff(head) is None

    def test_media_type_only_for_types_we_store(self):
        assert media_type_for(".png") == "image/png"
        assert media_type_for(".JPG") == "image/jpeg"
        assert media_type_for(".html") is None
        assert media_type_for(".svg") is None
        assert media_type_for("") is None


class TestUploadEndpoint:
    def test_html_body_declared_as_png_is_rejected(self, client):
        before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
        r = client.post(
            "/api/receipts/upload",
            files={"file": ("x.html", HTML, "image/png")},
            follow_redirects=False,
        )
        assert r.status_code == 400
        assert _new_files(before) == [], "a rejected upload still hit the disk"

    def test_extension_comes_from_the_bytes_not_the_filename(self, client):
        before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
        r = client.post(
            "/api/receipts/upload",
            files={"file": ("evil.html", PNG, "application/octet-stream")},
            follow_redirects=False,
        )
        assert r.status_code in (200, 303)
        written = _new_files(before)
        assert len(written) == 1
        assert written[0].suffix == ".png", "the client's extension was trusted"

    def test_oversize_upload_is_refused(self, client):
        before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
        r = client.post(
            "/api/receipts/upload",
            files={"file": ("big.png", PNG + b"\x00" * (10 * 1024 * 1024), "image/png")},
            follow_redirects=False,
        )
        assert r.status_code == 400
        assert _new_files(before) == []


class TestBulkUploadEndpoint:
    def test_rejects_unrecognised_content_and_keeps_the_good_one(self, client):
        before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
        r = client.post(
            "/api/bulk/upload",
            files=[
                ("files", ("a.png", HTML, "image/png")),
                ("files", ("b.jpg", JPG, "image/jpeg")),
            ],
        )
        assert r.status_code == 200
        written = _new_files(before)
        assert [p.suffix for p in written] == [".jpg"]

    def test_per_file_size_cap(self, client):
        before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
        r = client.post(
            "/api/bulk/upload",
            files=[("files", ("big.jpg", JPG + b"\x00" * (10 * 1024 * 1024), "image/jpeg"))],
        )
        assert r.status_code == 200
        assert _new_files(before) == [], "the bulk endpoint had no per-file cap"


class TestServingUploads:
    def test_stored_html_is_not_served(self, client):
        """Files predating the upload checks must not come back as text/html."""
        UPLOADS.mkdir(parents=True, exist_ok=True)
        stray = UPLOADS / "test-finding-11-stray.html"
        stray.write_bytes(HTML)
        try:
            r = client.get(f"/uploads/{stray.name}")
            assert r.status_code == 404
        finally:
            stray.unlink(missing_ok=True)

    def test_png_is_served_with_an_explicit_image_type(self, client):
        before = set(UPLOADS.iterdir()) if UPLOADS.exists() else set()
        client.post(
            "/api/receipts/upload",
            files={"file": ("shot.png", PNG, "image/png")},
            follow_redirects=False,
        )
        written = _new_files(before)
        assert len(written) == 1
        r = client.get(f"/uploads/{written[0].name}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"

    @pytest.mark.parametrize("attempt", ["../../.env", "..%2f..%2f.env", "nope.png"])
    def test_traversal_and_missing_files_are_404(self, client, attempt):
        r = client.get(f"/uploads/{attempt}")
        assert r.status_code == 404
        assert b"SECRET_KEY" not in r.content
