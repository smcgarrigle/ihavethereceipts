"""CM-06: lessons get a durable identity, a usage log and override state.

Correction rows are deleted and re-created whenever a review is saved again, so
anything that refers to a lesson — how often it was used, whether a person
suppressed or pinned it — has to refer to its content, not its row id.
"""

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import CorrectionOverride, CorrectionUsage, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import input_type_of

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "c4f1d8a2b907_correction_usage_and_overrides.py"
)


@pytest.fixture(scope="module")
def migration():
    spec = importlib.util.spec_from_file_location("cm06_migration", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_same_lesson_same_key():
    assert content_key(1, "image", "name", "MLK", "Milk") == content_key(
        1, "image", "name", "  MLK ", "Milk "
    )


def test_every_part_of_the_lesson_changes_the_key():
    base = (1, "image", "name", "MLK", "Milk")
    variants = [
        base,
        (None, "image", "name", "MLK", "Milk"),
        (2, "image", "name", "MLK", "Milk"),
        (1, "paste", "name", "MLK", "Milk"),
        (1, "image", "price", "MLK", "Milk"),
        (1, "image", "name", "MLKK", "Milk"),
        (1, "image", "name", "MLK", "milk"),
        (1, "image", "name", None, "Milk"),
    ]
    assert len({content_key(*v) for v in variants}) == len(variants)


def test_parts_cannot_run_together():
    """'a b' + 'c' must not collide with 'a' + 'b c' style splits."""
    assert content_key(1, "image", "name", "A1", "B") != content_key(1, "image", "name", "A", "1B")


@pytest.mark.parametrize(
    "case",
    [
        (1, "image", "name", "MLK", "Milk"),
        (None, "paste", "price", "4.34", "8.68"),
        (7, "pdf", "item_missed", None, "CRV"),
        (3, "image", "item_hallucinated", " Bag Refund ", None),
    ],
)
def test_migration_copy_of_the_key_matches_the_application(migration, case):
    assert migration._content_key(*case) == content_key(*case)


@pytest.mark.parametrize(
    "path", [None, "", "/data/uploads/a.jpg", "/data/uploads/a.PDF", "/x/b.pdf"]
)
def test_migration_copy_of_input_type_matches_the_application(migration, path):
    assert migration._input_type_of(path) == input_type_of(path)


def _reviewed_receipt(db, image_path):
    store = db.query(Store).filter_by(name="Costco").first()
    if not store:
        store = Store(name="Costco")
        db.add(store)
        db.commit()
    receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime(2026, 7, 1),
        total_amount=3.99,
        status="completed",
        image_path=image_path,
        ocr_data=json.dumps({"items": [{"name": "ORG SPNCH", "final_price": 3.99, "quantity": 1}]}),
    )
    db.add(receipt)
    db.commit()
    return receipt


def _save_review(client, receipt_id):
    resp = client.post(
        f"/api/receipts/{receipt_id}/save-reviewed-items",
        json={
            "items": [
                {
                    "name": "Organic Spinach",
                    "base_price": 3.99,
                    "quantity": 1.0,
                    "discounts": [],
                    "fees": [],
                    "final_price": 3.99,
                }
            ],
            "store_name": "Costco",
        },
    )
    assert resp.status_code == 200 and resp.json()["success"]


def test_review_save_records_kind_and_key(client, db):
    receipt = _reviewed_receipt(db, "/data/uploads/spinach.jpg")
    _save_review(client, receipt.id)

    row = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()
    assert row.input_type == "image"
    assert row.content_key == content_key(
        row.store_id, "image", "name", "ORG SPNCH", "Organic Spinach"
    )


def test_pasted_receipt_records_paste(client, db):
    receipt = _reviewed_receipt(db, None)
    _save_review(client, receipt.id)

    row = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one()
    assert row.input_type == "paste"


def test_key_survives_a_resave(client, db):
    """The row is re-created on every save; the lesson's identity is not."""
    receipt = _reviewed_receipt(db, "/data/uploads/spinach.jpg")
    _save_review(client, receipt.id)
    first = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").one().content_key

    _save_review(client, receipt.id)
    db.expire_all()
    rows = db.query(OcrCorrection).filter_by(receipt_id=receipt.id, field="name").all()

    assert len(rows) == 1
    assert rows[0].content_key == first


def test_one_override_per_lesson(db):
    key = content_key(1, "image", "name", "MLK", "Milk")
    db.add(CorrectionOverride(content_key=key, input_type="image", field="name", suppressed=True))
    db.commit()

    db.add(CorrectionOverride(content_key=key, input_type="image", field="name", pinned=True))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_override_defaults_to_neither_suppressed_nor_pinned(db):
    override = CorrectionOverride(
        content_key=content_key(None, "pdf", "name", "A", "B"), input_type="pdf", field="name"
    )
    db.add(override)
    db.commit()
    db.refresh(override)

    assert override.suppressed is False
    assert override.pinned is False
    assert override.updated_at is not None


def test_usage_row_records_receipt_and_time(db):
    receipt = _reviewed_receipt(db, "/data/uploads/spinach.jpg")
    usage = CorrectionUsage(
        content_key=content_key(receipt.store_id, "image", "name", "ORG SPNCH", "Organic Spinach"),
        receipt_id=receipt.id,
    )
    db.add(usage)
    db.commit()
    db.refresh(usage)

    assert usage.id is not None
    assert usage.used_at is not None
