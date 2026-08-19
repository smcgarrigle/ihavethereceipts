"""Settings router — Exclusions Manager page and CRUD API.

Also provides:
  - Feature flag read/write (USDA lookup toggle)
  - Data deletion endpoint
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session


class DeleteConfirmation(BaseModel):
    confirmation: str = ""


from app.api.templates import templates  # noqa: E402
from app.database import get_db  # noqa: E402
from app.models.exclusion import ExclusionRule  # noqa: E402
from app.services import predictions as predictions_service  # noqa: E402

logger = logging.getLogger(__name__)
router = APIRouter()

OCR_FILTERS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "ocr_filters.json"
)
FEATURE_FLAGS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "feature_flags.json"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_ocr_filters() -> dict[str, Any]:
    try:
        with open(OCR_FILTERS_PATH) as f:
            return dict(json.load(f))
    except Exception:
        return {"skip_keywords": [], "junk_filters": []}


def _save_ocr_filters(data: dict) -> None:
    with open(OCR_FILTERS_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_feature_flags() -> dict[str, Any]:
    try:
        with open(FEATURE_FLAGS_PATH) as f:
            return dict(json.load(f))
    except Exception:
        return {"usda_lookup_enabled": True}


def _save_feature_flags(data: dict) -> None:
    FEATURE_FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FEATURE_FLAGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    """Primary settings page — USDA toggle, exclusions, and danger zone."""
    return _render_settings_page(request, db)


@router.get("/exclusions", response_class=HTMLResponse)
def exclusions_page_redirect(_request: Request) -> RedirectResponse:
    """Legacy redirect — /settings/exclusions now lives at /settings."""
    return RedirectResponse(url="/settings", status_code=301)


def _render_settings_page(request: Request, db: Session) -> HTMLResponse:
    """Shared render logic for the settings page."""
    analytics_rules = (
        db.query(ExclusionRule)
        .filter(ExclusionRule.scope == "analytics")
        .order_by(ExclusionRule.pattern)
        .all()
    )
    prediction_rules = (
        db.query(ExclusionRule)
        .filter(ExclusionRule.scope == "predictions")
        .order_by(ExclusionRule.pattern)
        .all()
    )
    ocr = _load_ocr_filters()
    flags = _load_feature_flags()

    # Active OCR model + today's call count. Previously a badge in the receipts
    # page header; it belongs here next to the OCR success rating.
    import os

    from app.services.ocr import get_backend, get_daily_usage

    backend = get_backend()
    ocr_model_name = (
        os.getenv("OCR_MODEL", "llava:7b")
        if backend == "local"
        else os.getenv("GEMINI_MODEL_NAME", "gemini-flash")
    )

    return templates.TemplateResponse(
        request,
        "pages/settings.html",
        {
            "analytics_rules": analytics_rules,
            "prediction_rules": prediction_rules,
            "skip_keywords": ocr.get("skip_keywords", []),
            "junk_filters": ocr.get("junk_filters", []),
            "usda_lookup_enabled": flags.get("usda_lookup_enabled", True),
            "nutrition_outlier_percentile": flags.get("nutrition_outlier_percentile", 95),
            "protein_roi_target": flags.get("protein_roi_target", 0.20),
            "ocr_backend": backend,
            "ocr_model": ocr_model_name,
            "ocr_usage": get_daily_usage(),
        },
    )


# ---------------------------------------------------------------------------
# DB-backed rules (analytics + predictions)
# ---------------------------------------------------------------------------


@router.post("/exclusions/rules", response_class=HTMLResponse)
def add_rule(
    request: Request,
    db: Session = Depends(get_db),
    scope: str = Form(""),
    pattern: str = Form(""),
    reason: str = Form(""),
):
    """Add an exclusion rule. Returns an updated list fragment for the relevant scope."""
    pattern = pattern.strip()
    reason = reason.strip()

    if not pattern or scope not in ("analytics", "predictions"):
        return HTMLResponse("<p class='text-red-500 text-sm'>Invalid scope or empty pattern.</p>")

    # Avoid duplicates
    existing = (
        db.query(ExclusionRule)
        .filter(ExclusionRule.scope == scope, ExclusionRule.pattern == pattern)
        .first()
    )
    if not existing:
        rule = ExclusionRule(scope=scope, pattern=pattern, reason=reason.strip() or None)
        db.add(rule)
        db.commit()
        # Invalidate prediction cache so new rules take effect immediately
        predictions_service._cadence_cache["data"] = None

    return _render_rules_list(request, db, scope)


@router.delete("/exclusions/rules/{rule_id}", response_class=HTMLResponse)
def delete_rule(rule_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete an exclusion rule and return the updated list for that scope."""
    rule = db.query(ExclusionRule).filter(ExclusionRule.id == rule_id).first()
    if rule:
        scope = rule.scope
        db.delete(rule)
        db.commit()
        predictions_service._cadence_cache["data"] = None
        return _render_rules_list(request, db, scope)
    return HTMLResponse("")


def _render_rules_list(request: Request, db: Session, scope: str) -> HTMLResponse:
    rules = (
        db.query(ExclusionRule)
        .filter(ExclusionRule.scope == scope)
        .order_by(ExclusionRule.pattern)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "fragments/exclusion_rules_list.html",
        {"rules": rules, "scope": scope},
    )


# ---------------------------------------------------------------------------
# JSON-backed OCR filters
# ---------------------------------------------------------------------------


@router.post("/exclusions/ocr/{filter_type}", response_class=HTMLResponse)
def add_ocr_filter(filter_type: str, request: Request, value: str = Form("")):
    """Add a skip keyword or junk filter. Returns the updated list fragment."""
    value = value.strip()
    if filter_type not in ("skip_keywords", "junk_filters") or not value:
        return HTMLResponse(
            "<p class='text-red-500 text-sm'>Invalid filter type or empty value.</p>"
        )

    data = _load_ocr_filters()
    if value not in data.get(filter_type, []):
        data.setdefault(filter_type, []).append(value)
        _save_ocr_filters(data)

    return _render_ocr_list(request, filter_type, data[filter_type])


@router.delete("/exclusions/ocr/{filter_type}", response_class=HTMLResponse)
def delete_ocr_filter(filter_type: str, request: Request, value: str = ""):
    """Remove a skip keyword or junk filter by value."""
    if filter_type not in ("skip_keywords", "junk_filters"):
        return HTMLResponse("")

    data = _load_ocr_filters()
    items = data.get(filter_type, [])
    data[filter_type] = [i for i in items if i != value]
    _save_ocr_filters(data)
    return _render_ocr_list(request, filter_type, data[filter_type])


def _render_ocr_list(request: Request, filter_type: str, items: list) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "fragments/ocr_filter_list.html",
        {"filter_type": filter_type, "items": items},
    )


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------


@router.get("/flags")
def get_flags() -> JSONResponse:
    """Return current feature flag state."""
    return JSONResponse(_load_feature_flags())


@router.post("/flags/usda-lookup")
def toggle_usda_lookup(enabled: bool) -> JSONResponse:
    """Enable or disable USDA enrichment lookups globally. Existing data is preserved."""
    flags = _load_feature_flags()
    flags["usda_lookup_enabled"] = enabled
    _save_feature_flags(flags)
    logger.info("USDA lookup %s via settings toggle.", "enabled" if enabled else "disabled")
    return JSONResponse({"success": True, "usda_lookup_enabled": enabled})


@router.post("/flags/nutrition-outlier-percentile")
def set_nutrition_outlier_percentile(percentile: int) -> JSONResponse:
    """Set the percentile cutoff for nutrition outlier capping (0 = off)."""
    from app.api.trends_nutrition import ALLOWED_PERCENTILES

    if percentile not in ALLOWED_PERCENTILES:
        return JSONResponse(
            {
                "success": False,
                "error": f"Percentile must be one of {sorted(ALLOWED_PERCENTILES)}.",
            },
            status_code=422,
        )
    flags = _load_feature_flags()
    flags["nutrition_outlier_percentile"] = percentile
    _save_feature_flags(flags)
    logger.info("Nutrition outlier percentile set to %s via settings.", percentile)
    return JSONResponse({"success": True, "nutrition_outlier_percentile": percentile})


@router.post("/flags/protein-roi-target")
def set_protein_roi_target(target: float) -> JSONResponse:
    """Set the cost-per-gram-of-protein target used to color the Protein ROI ranking."""
    if not (0.01 <= target <= 5.00):
        return JSONResponse(
            {"success": False, "error": "Target must be between $0.01 and $5.00 per gram."},
            status_code=422,
        )
    target = round(target, 2)
    flags = _load_feature_flags()
    flags["protein_roi_target"] = target
    _save_feature_flags(flags)
    logger.info("Protein ROI target set to $%s/g via settings.", target)
    return JSONResponse({"success": True, "protein_roi_target": target})


# ---------------------------------------------------------------------------
# Data deletion
# ---------------------------------------------------------------------------


@router.delete("/data/all")
def delete_all_data(body: "DeleteConfirmation", db: Session = Depends(get_db)) -> JSONResponse:
    """Permanently delete all user data.

    Requires JSON body: {"confirmation": "i understand"} (case-insensitive).
    Preserves database schema — only truncates data rows.
    """
    confirmation = (body.confirmation or "").strip().lower()
    if confirmation != "i understand":
        return JSONResponse(
            {"success": False, "error": "Confirmation text did not match."}, status_code=403
        )

    try:
        from app.models.item import Item, ItemMatchIgnore
        from app.models.receipt import Receipt, ReceiptItem
        from app.models.store import Store

        # Delete in dependency order (children before parents)
        db.query(ItemMatchIgnore).delete()
        db.query(ReceiptItem).delete()
        db.query(Receipt).delete()
        db.query(Item).delete()
        db.query(Store).delete()
        db.query(ExclusionRule).delete()
        db.commit()

        logger.warning("All user data deleted via settings page.")
        return JSONResponse({"success": True, "message": "All data deleted successfully."})
    except Exception as e:
        db.rollback()
        logger.error("Data deletion failed: %s", e)
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
