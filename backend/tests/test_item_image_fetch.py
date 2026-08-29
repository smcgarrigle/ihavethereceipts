"""Guards on PUT /api/items/{id}/image.

The endpoint used to hand ``image_url`` straight to ``urllib.request.urlopen``
and take the stored file extension from the URL. Because urllib handles
``file://``, ``{"image_url": "file:///.../.env"}`` copied the environment file —
API keys and SECRET_KEY — into the statically served uploads directory, where it
could then be fetched over HTTP. The same call reached any host on the LAN.

These tests fail against that implementation.
"""

import pytest

from app.models import Category, Item
from app.utils.safe_fetch import UnsafeURLError, fetch_remote_image


@pytest.fixture
def item(db):
    category = Category(name="Pantry")
    db.add(category)
    db.flush()

    item = Item(name="Olive Oil", normalized_name="olive oil", category_id=category.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file:///home/user/grocery-tracker/.env",
        "ftp://example.com/image.jpg",
        "gopher://example.com/image.jpg",
        "/etc/passwd",
    ],
)
def test_non_http_schemes_are_refused(url):
    with pytest.raises(UnsafeURLError):
        fetch_remote_image(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:11434/api/tags",
        "http://localhost:8000/api/export/all/csv",
        "http://192.168.1.1/",
        "http://10.0.0.5/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8000/",
    ],
)
def test_private_and_loopback_hosts_are_refused(url):
    with pytest.raises(UnsafeURLError):
        fetch_remote_image(url)


def test_endpoint_rejects_file_scheme_without_writing(client, item, tmp_path):
    """The request must be refused before anything touches the filesystem."""
    secret = tmp_path / ".env"
    secret.write_text("GEMINI_API_KEY=super-secret\nSECRET_KEY=also-secret\n")

    response = client.put(
        f"/api/items/{item.id}/image",
        json={"image_url": f"file://{secret}"},
    )

    assert response.status_code == 400, (
        "A file:// URL must be rejected outright. Anything else means urllib "
        "read a local file for an unauthenticated caller."
    )
    assert item.image_path is None


def test_endpoint_rejects_lan_address(client, item):
    response = client.put(
        f"/api/items/{item.id}/image",
        json={"image_url": "http://192.168.1.1/router.png"},
    )

    assert response.status_code == 400
    assert item.image_path is None


def test_extension_comes_from_content_type_not_url(monkeypatch, client, item):
    """A URL ending in .env must not produce a .env file on disk."""
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return b"\x89PNG\r\n\x1a\n", "png"

    monkeypatch.setattr("app.utils.safe_fetch.fetch_remote_image", fake_fetch)

    response = client.put(
        f"/api/items/{item.id}/image",
        json={"image_url": "https://example.com/photo.env?x=1"},
    )

    assert response.status_code == 200
    assert response.json()["image_path"].endswith(".png")
    assert not response.json()["image_path"].endswith(".env")
