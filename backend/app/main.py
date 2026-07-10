import logging
import os
from pathlib import Path

logger = logging.getLogger("app.main")

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Load environment variables
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
    from pathlib import Path

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


app = FastAPI(title="Grocery Price Tracker", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.middleware import (
    ContentLengthLimitMiddleware,
    CSRFMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)

# CORS Configuration
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
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

# Mount static files
BASE_DIR = Path(__file__).resolve().parent.parent
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
# Uploads are saved in project_root/data/uploads, which is one level up from backend
app.mount(
    "/uploads",
    StaticFiles(directory=str(BASE_DIR.parent / "data" / "uploads")),
    name="uploads",
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
