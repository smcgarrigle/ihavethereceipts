import logging
import os
from pathlib import Path

logger = logging.getLogger("app.main")

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.utils.upload_validation import media_type_for

# Load environment variables. Skipped under TESTING so .env cannot override
# the test environment (see app/core/config.py for the full rationale).
if os.getenv("TESTING") != "1":
    load_dotenv(override=True)

from contextlib import asynccontextmanager

from app.api import (
    analytics,
    analytics_fragments,
    bulk,
    categories,
    export,
    items,
    predictions_router,
    receipts,
    receipts_fragments,
    receipts_review,
    search_router,
    settings_router,
    trends,
    trends_nutrition,
    xray,
)
from app.database import DATABASE_URL
from app.services.model_manager import model_manager


def run_migrations() -> None:
    """Apply Alembic migrations at startup — the single schema authority.

    Replaces the old import-time Base.metadata.create_all(), which could
    silently diverge from migration history on fresh environments.
    Set AUTO_MIGRATE=0 to manage migrations manually.
    """
    from pathlib import Path  # noqa: I001

    from alembic import command
    from alembic.config import Config as AlembicConfig

    cfg = AlembicConfig(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")
    print("Database schema: alembic upgrade head applied")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.getenv("TESTING") != "1" and os.getenv("AUTO_MIGRATE", "1") == "1":
        run_migrations()

    ocr_backend = os.getenv("OCR_BACKEND", "local").lower()
    if ocr_backend == "gemini":
        try:
            print("Application startup: Validating Gemini models...")
            await model_manager.ensure_models_updated()
        except Exception as e:
            print(f"Startup warning: Failed to check models: {e}")
    else:
        # Show local info if local backend selected (dynamic lookup)
        from app.services.ocr import get_backend

        backend = get_backend()
        ocr_model = "N/A"  # Initialize with default
        ocr_url = "N/A"  # Initialize with default
        if backend == "local":
            ocr_model = os.getenv("OCR_MODEL", "llava:7b")
            ocr_url = os.getenv("OCR_BACKEND_URL", "http://localhost:11434/v1")
        elif backend == "openrouter":
            from app.services.ocr import OPENROUTER_URL

            ocr_model = os.getenv("OCR_MODEL") or "not set"
            ocr_url = os.getenv("OPENROUTER_BASE_URL") or OPENROUTER_URL
            if not os.getenv("OPENROUTER_API_KEY"):
                print("⚠ OCR_BACKEND=openrouter but OPENROUTER_API_KEY is not set — OCR will fail.")
            if not os.getenv("OCR_MODEL"):
                print("⚠ OCR_BACKEND=openrouter but OCR_MODEL is not set — OCR will fail.")
            print(
                "⚠ OpenRouter is a hosted third party: receipt images leave this machine. "
                "Sending provider.data_collection=deny"
                + (
                    " (DISABLED via OPENROUTER_ALLOW_TRAINING=1)"
                    if os.getenv("OPENROUTER_ALLOW_TRAINING") == "1"
                    else ""
                )
                + "."
            )
        print(f"Application startup: OCR backend = {backend.upper()} ({ocr_model} @ {ocr_url})")
    # Clean up any orphaned receipts stuck in "processing" due to unexpected shutdown
    try:
        from app.database import SessionLocal
        from app.models import Receipt

        db = SessionLocal()
        stuck = db.query(Receipt).filter(Receipt.status == "processing").all()
        for r in stuck:
            r.status = "failed"
            r.error_message = "Process aborted (server restart)"
        if stuck:
            db.commit()
            print(f"🧹 Cleaned up {len(stuck)} orphaned receipts")
        db.close()
    except Exception as e:
        print(f"Failed to clean up orphaned receipts: {e}")

    # Starting BulkProcessor
    from app.services.bulk_processor import bulk_processor

    bulk_processor.start()
    print("🚀 BulkProcessor service started")

    # Folder-watch ingester (data/inbox; disable with FOLDER_WATCH=0)
    from app.services.folder_watch import folder_watcher

    if os.getenv("TESTING") != "1":
        folder_watcher.start()

    yield
    # Shutdown logic
    folder_watcher.stop()
    bulk_processor.stop()


app = FastAPI(title="IHaveTheReceipts", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.middleware import (
    ContentLengthLimitMiddleware,
    CSRFMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)


def _cors_origins() -> list[str]:
    """Explicit cross-origin callers, or empty meaning: do not enable CORS.

    A wildcard is deliberately read as "unset" rather than as permission.
    Starlette does not emit a literal ``*`` when credentials are allowed -- it
    reflects whatever Origin the request carried -- so ``ALLOWED_ORIGINS=*``
    combined with ``allow_credentials=True`` lets any page the user happens to
    visit read the whole purchase history back off loopback. The UI is
    same-origin HTMX and needs no CORS at all, so the safe reading of "*" is
    none rather than every.
    """
    raw = os.getenv("ALLOWED_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in origins:
        return []
    return origins


def _trusted_hosts() -> list[str]:
    """Host headers the app answers to.

    There is no authentication, so start_server.sh binds loopback and documents
    ``tailscale serve`` as the way to reach it from another device. Those are
    the hosts it should answer on; without the check, DNS rebinding is a way
    around the loopback bind. Widen with ALLOWED_HOSTS when binding elsewhere.
    """
    raw = os.getenv("ALLOWED_HOSTS", "").strip()
    if raw:
        return [h.strip() for h in raw.split(",") if h.strip()]
    if os.getenv("TESTING"):
        return ["*"]
    return ["localhost", "127.0.0.1", "*.ts.net"]


# CORS is off unless someone names the origins that need it.
_origins = _cors_origins()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Security Headers and CSP
app.add_middleware(SecurityHeadersMiddleware)

# Rate Limiting (20 upload/reprocess requests per 60s per IP)
app.add_middleware(RateLimitMiddleware)

# Payload Size Limit (15MB maximum request size)
app.add_middleware(ContentLengthLimitMiddleware)

# CSRF Protection Groundwork
app.add_middleware(CSRFMiddleware)

# Session Middleware (required for CSRF) - Added AFTER so it is OUTER
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "unsafe-default-key-change-this"),
    max_age=3600 * 24 * 7,  # 1 week
)

# Host validation, added last so it is outermost and rejects before anything
# else runs.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_trusted_hosts())

# Mount static files
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# Uploads are saved in project_root/data/uploads, which is one level up from
# backend. They are NOT mounted as StaticFiles: that served each file under the
# extension it was stored with, so anything that got past the old upload check
# came back with a content type of its own choosing -- text/html included, on
# this origin and under this CSP. Serving them by hand means the content type is
# one of ours or the file is not served at all.
UPLOADS_DIR = (BASE_DIR.parent / "data" / "uploads").resolve()


@app.get("/uploads/{filename}", name="uploads")
def serve_upload(filename: str) -> FileResponse:
    media_type = media_type_for(Path(filename).suffix)
    if media_type is None:
        raise HTTPException(status_code=404)

    # Names are UUIDs we generated, but resolve and confine anyway.
    path = (UPLOADS_DIR / Path(filename).name).resolve()
    if path.parent != UPLOADS_DIR or not path.is_file():
        raise HTTPException(status_code=404)

    return FileResponse(
        path,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


# Templates

# Include API routers
app.include_router(receipts.router, prefix="/api/receipts", tags=["receipts"])
app.include_router(receipts_review.router, prefix="/api/receipts", tags=["receipts"])
app.include_router(receipts_fragments.router, prefix="/api/receipts", tags=["receipts"])
app.include_router(items.router, prefix="/api/items", tags=["items"])
app.include_router(categories.router, prefix="/api/categories", tags=["categories"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(analytics_fragments.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(trends.router, prefix="/api/trends", tags=["trends"])
app.include_router(trends_nutrition.router, prefix="/api/trends", tags=["trends"])
app.include_router(bulk.router, prefix="/api/bulk", tags=["bulk"])
app.include_router(export.router, prefix="/api/export", tags=["export"])
app.include_router(predictions_router.router, prefix="/api/predictions", tags=["predictions"])
app.include_router(search_router.router, prefix="/api", tags=["search"])
app.include_router(settings_router.router, prefix="/settings", tags=["settings"])
app.include_router(xray.router, prefix="/api/analytics", tags=["xray"])

# Page routes (server-rendered HTML) — see app/api/pages.py
from app.api import pages

app.include_router(pages.router, tags=["pages"])
