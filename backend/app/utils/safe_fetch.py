"""Fetch remote images without turning the app into a file reader or a LAN proxy.

``urllib`` happily handles ``file://`` and ``ftp://``, so passing a user-supplied
string straight to ``urlopen`` is an arbitrary local file read. Resolving the
host is not enough either — a public hostname can point at ``127.0.0.1`` and a
redirect can hop to the router's admin page after the check has passed.

The rules here are deliberately strict, because the only caller needs one thing:
pull a product photo off a public web server.
"""

import ipaddress
import logging
import socket
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = ("http", "https")

# Content-Type -> extension. The extension comes from what the server actually
# sent and never from the URL, so a crafted path cannot pick the extension the
# file is stored under.
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024
FETCH_TIMEOUT_SECONDS = 10
USER_AGENT = "GroceryTracker/1.0"


class UnsafeURLError(ValueError):
    """The URL is not a fetchable public http(s) image URL."""


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Block redirects outright.

    Validating the host before the request is pointless if the server can then
    redirect to ``http://192.168.1.1/``, and re-validating each hop is more
    machinery than an image fetch warrants.
    """

    def redirect_request(self, _req, _fp, _code, _msg, _headers, newurl):
        raise UnsafeURLError(f"Refusing to follow redirect to {newurl}")


_opener = urllib.request.build_opener(_RefuseRedirects)


def _assert_public_host(host: str) -> None:
    """Raise unless every address the host resolves to is publicly routable."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURLError(f"Could not resolve host {host!r}") from e

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as e:
            raise UnsafeURLError(f"Host {host!r} resolved to {address!r}") from e

        # is_global already excludes private, loopback, link-local, and reserved
        # ranges; the rest are named so the intent survives a reading.
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise UnsafeURLError(
                f"Host {host!r} resolves to non-public address {address} — refusing to fetch"
            )


def fetch_remote_image(url: str) -> tuple[bytes, str]:
    """Download a public http(s) image, returning ``(bytes, extension)``.

    Raises :class:`UnsafeURLError` for any scheme other than http/https, any
    host that resolves into a private range, a redirect, a non-image
    Content-Type, or a body over :data:`MAX_IMAGE_BYTES`.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"Scheme {parsed.scheme or '(none)'!r} is not allowed — use http or https"
        )
    if not parsed.hostname:
        raise UnsafeURLError("URL has no host")

    _assert_public_host(parsed.hostname)

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        extension = CONTENT_TYPE_EXTENSIONS.get(response.headers.get_content_type())
        if extension is None:
            raise UnsafeURLError(
                f"Content-Type {response.headers.get_content_type()!r} is not a supported image"
            )

        declared_length = response.headers.get("Content-Length")
        if declared_length and declared_length.isdigit() and int(declared_length) > MAX_IMAGE_BYTES:
            raise UnsafeURLError(f"Image is larger than {MAX_IMAGE_BYTES} bytes")

        # Read one byte past the cap so a missing/lying Content-Length is caught.
        data = response.read(MAX_IMAGE_BYTES + 1)

    if len(data) > MAX_IMAGE_BYTES:
        raise UnsafeURLError(f"Image is larger than {MAX_IMAGE_BYTES} bytes")

    return data, extension
