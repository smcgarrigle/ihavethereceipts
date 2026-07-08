import os
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class CSRFMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, exempt_path_prefixes: list[str] | None = None):
        super().__init__(app)
        self.exempt_path_prefixes = exempt_path_prefixes or ["/static", "/uploads", "/favicon.ico"]

    async def dispatch(self, request: Request, call_next):
        # 0. Skip validation if in test environment
        if os.getenv("TESTING") == "1":
            return await call_next(request)

        # 1. Skip validation for safe methods
        if request.method in ("GET", "HEAD", "OPTIONS", "TRACE"):
            # Ensure a token exists in the session for future use
            if "csrf_token" not in request.session:
                request.session["csrf_token"] = secrets.token_urlsafe(32)

            response = await call_next(request)
            return response

        # 2. Skip validation for exempt paths
        for prefix in self.exempt_path_prefixes:
            if request.url.path.startswith(prefix):
                return await call_next(request)

        # 3. Validate token for state-changing methods
        session_token = request.session.get("csrf_token")

        # Check Header (common for AJAX/HTMX)
        header_token = request.headers.get("X-CSRF-Token")

        # Check Form Data (common for standard HTML forms)
        form_token = None
        if not header_token and "application/x-www-form-urlencoded" in request.headers.get(
            "Content-Type", ""
        ):
            try:
                # Read body and reconstruct the receive stream for downstream handlers
                body = await request.body()

                async def receive():
                    return {"type": "http.request", "body": body}

                request.scope["receive"] = receive
                request._receive = receive

                form_data = await request.form()
                form_token = form_data.get("csrf_token")
            except Exception as e:
                import logging

                logger = logging.getLogger("app.middleware")
                logger.error(f"CSRF middleware failed to parse form data: {e}")
                raise HTTPException(
                    status_code=403, detail="CSRF form validation failed: unable to parse form data"
                ) from e

        # Validation logic
        if not session_token:
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF session token missing. Please refresh the page."},
            )

        if not header_token and not form_token:
            return JSONResponse(
                status_code=403, content={"detail": "CSRF token missing from request."}
            )

        if header_token != session_token and form_token != session_token:
            return JSONResponse(status_code=403, content={"detail": "CSRF token mismatch."})

        return await call_next(request)


class ContentLengthLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_content_length: int = 15 * 1024 * 1024):  # Default 15 MB
        super().__init__(app)
        self.max_content_length = max_content_length

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            content_length_header = request.headers.get("content-length")
            if content_length_header:
                try:
                    content_length = int(content_length_header)
                    if content_length > self.max_content_length:
                        return JSONResponse(
                            status_code=413,
                            content={"detail": "Payload too large. Maximum size allowed is 15MB."},
                        )
                except ValueError:
                    return JSONResponse(
                        status_code=400, content={"detail": "Invalid Content-Length header."}
                    )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limit: int = 20, window_seconds: int = 60, max_clients: int = 1024):
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self.requests: dict[str, list[float]] = {}  # ip_address -> list of timestamps

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/receipts/upload") or path.endswith("/reprocess"):
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()

            # Clean up old timestamps
            timestamps = self.requests.get(client_ip, [])
            timestamps = [t for t in timestamps if now - t < self.window_seconds]

            if len(timestamps) >= self.limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                )

            timestamps.append(now)
            self.requests[client_ip] = timestamps

            # Bound memory: sweep idle IPs once the dict outgrows the cap, so
            # unique clients can't grow it without limit
            if len(self.requests) > self.max_clients:
                cutoff = now - self.window_seconds
                self.requests = {
                    ip: ts for ip, ts in self.requests.items() if ts and ts[-1] > cutoff
                }

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Self-contained CSP: all assets are vendored/precompiled, no external hosts.
        # 'unsafe-eval' stays because Alpine.js builds expression evaluators via the
        # AsyncFunction constructor; 'unsafe-inline' covers inline Alpine/HTMX markup.
        csp_directives = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self' data:; "
            "img-src 'self' data:; "
            "connect-src 'self';"
        )
        response.headers["Content-Security-Policy"] = csp_directives
        return response
