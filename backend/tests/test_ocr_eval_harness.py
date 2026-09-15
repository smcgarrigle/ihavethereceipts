"""CM-01: the eval harness measures the prompt production actually sends.

Before this, ``ocr_eval.py --live`` called the OCR functions with no
``prompt_extra``, so it benchmarked a prompt production never sends and could
not measure any change to the corrections block. It also scored the catalog
name auto-merge wrote over the model's read, which credited stored runs with a
rename a live run never gets.
"""

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_service import get_correction_prompt

HARNESS = Path(__file__).resolve().parent.parent / "scripts" / "ocr_eval.py"


@pytest.fixture(scope="module")
def harness():
    spec = importlib.util.spec_from_file_location("ocr_eval_under_test", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt_with_review(db, client, tmp_path, store_name, ai_name, reviewed_name, price):
    """A completed image receipt whose review recorded one name correction."""
    store = db.query(Store).filter_by(name=store_name).first()
    if not store:
        store = Store(name=store_name)
        db.add(store)
        db.commit()

    image = tmp_path / f"{store_name.replace(' ', '_')}_{ai_name.replace(' ', '_')}.jpg"
    image.write_bytes(b"\xff\xd8\xff")
    receipt = Receipt(
        store_id=store.id,
        purchase_date=datetime(2026, 7, 1),
        total_amount=price,
        status="completed",
        image_path=str(image),
        ocr_data=json.dumps(
            {
                "items": [{"name": ai_name, "final_price": price, "quantity": 1}],
                "total_amount": price,
            }
        ),
    )
    db.add(receipt)
    db.commit()

    resp = client.post(
        f"/api/receipts/{receipt.id}/save-reviewed-items",
        json={
            "items": [
                {
                    "name": reviewed_name,
                    "base_price": price,
                    "quantity": 1.0,
                    "discounts": [],
                    "fees": [],
                    "final_price": price,
                }
            ],
            "store_name": store_name,
        },
    )
    assert resp.status_code == 200 and resp.json()["success"]
    db.refresh(receipt)
    return receipt


def test_block_can_exclude_a_receipts_own_corrections(client, db, tmp_path):
    own = _receipt_with_review(db, client, tmp_path, "Costco", "ORG SPNCH", "Organic Spinach", 3.99)
    other = _receipt_with_review(
        db, client, tmp_path, "Costco", "KS ALMND BTR", "Kirkland Almond Butter", 11.49
    )

    everything = get_correction_prompt(db)
    assert "ORG SPNCH" in everything and "KS ALMND BTR" in everything

    without_own = get_correction_prompt(db, exclude_receipt_ids=[own.id])
    assert "ORG SPNCH" not in without_own, "the scored receipt's own answer leaked into its prompt"
    assert "KS ALMND BTR" in without_own
    assert other.id != own.id


def test_live_run_sends_the_production_block_without_leakage(harness, client, db, tmp_path):
    scored = _receipt_with_review(
        db, client, tmp_path, "Costco", "ORG SPNCH", "Organic Spinach", 3.99
    )
    _receipt_with_review(db, client, tmp_path, "Safeway", "MLK WHL GAL", "Whole Milk", 4.29)

    seen: dict[str, str] = {}

    def fake_extract(path, prompt_extra):
        seen[path] = prompt_extra
        return {"items": [{"name": "Organic Spinach", "final_price": 3.99}], "total_amount": 3.99}

    result = harness.run_eval(
        db, receipt_ids=[scored.id], limit=1, live=True, corrections="global", extract=fake_extract
    )

    prompt = seen[scored.image_path]
    assert "LEARNED CORRECTIONS" in prompt, (
        "--live must send the corrections block production sends"
    )
    assert "MLK WHL GAL" in prompt, "global mode should include other stores' corrections"
    assert "ORG SPNCH" not in prompt, "the receipt's own correction must never be in its prompt"
    assert [r["receipt_id"] for r in result["rows"]] == [scored.id]


def test_store_mode_scopes_and_none_mode_sends_nothing(harness, client, db, tmp_path):
    scored = _receipt_with_review(
        db, client, tmp_path, "Costco", "ORG SPNCH", "Organic Spinach", 3.99
    )
    _receipt_with_review(
        db, client, tmp_path, "Costco", "KS ALMND BTR", "Kirkland Almond Butter", 11.49
    )
    _receipt_with_review(db, client, tmp_path, "Safeway", "MLK WHL GAL", "Whole Milk", 4.29)

    store_block = harness.build_prompt_extra(db, scored, "store")
    assert "KS ALMND BTR" in store_block and "MLK WHL GAL" not in store_block
    assert harness.build_prompt_extra(db, scored, "none") == ""


def test_ocr_errors_are_reported_not_averaged(harness, client, db, tmp_path):
    receipt = _receipt_with_review(
        db, client, tmp_path, "Costco", "ORG SPNCH", "Organic Spinach", 3.99
    )

    result = harness.run_eval(
        db,
        receipt_ids=[receipt.id],
        limit=1,
        live=True,
        extract=lambda _path, _extra: {"error": "Connection error."},
    )

    assert result["rows"] == []
    assert result["ocr_errors"] == [{"receipt_id": receipt.id, "error": "Connection error."}]


def test_name_is_scored_on_what_the_model_read(harness):
    """Auto-merge writes the catalog name over the model's read in stored data."""
    receipt = SimpleNamespace(
        id=1,
        store=SimpleNamespace(name="Whole Foods Market"),
        total_amount=4.99,
        items=[
            SimpleNamespace(
                item=SimpleNamespace(name="365WFM OG HMBRGR BUNS"), price=4.99, quantity=1
            )
        ],
    )
    merged = {
        "items": [
            {
                "name": "365 Organic Hamburger Buns",
                "original_ocr_name": "365WFM OG HMBRGR BUNS",
                "final_price": 4.99,
            }
        ],
        "total_amount": 4.99,
    }

    row = harness.score_receipt(merged, receipt)
    assert row["name_score"] == 100.0, "scored the catalog rename instead of the model's read"


@pytest.mark.parametrize(
    ("limit", "ids", "expected"),
    [(None, [459, 458, 457], 3), (None, None, 15), (5, [459, 458, 457], 5)],
)
def test_limit_defaults_to_the_requested_ids(harness, limit, ids, expected):
    assert harness.resolve_limit(limit, ids) == expected


def test_json_payload_records_what_was_run(harness):
    args = harness.parse_args(["--live", "--corrections", "store", "--receipt-ids", "1", "2"])
    result = {
        "rows": [
            {
                "receipt_id": 1,
                "item_recall": 1.0,
                "item_precision": 1.0,
                "name_score": 90.0,
                "price_acc": 1.0,
                "total_ok": 1,
            }
        ],
        "ocr_errors": [{"receipt_id": 2, "error": "timeout"}],
        "unscored": [],
    }

    payload = harness.build_payload(result, args)

    assert payload["mode"] == "live" and payload["corrections"] == "store"
    assert payload["requested_ids"] == [1, 2]
    assert payload["mean"]["name_score"] == 90.0
    assert payload["ocr_errors"][0]["receipt_id"] == 2
    json.dumps(payload)


def test_live_prompt_uses_the_receipts_input_type(harness, client, db, tmp_path):
    """A photographed receipt is scored with photo corrections only, as in production."""
    photo = _receipt_with_review(
        db, client, tmp_path, "Costco", "ORG SPNCH", "Organic Spinach", 3.99
    )
    _receipt_with_review(
        db, client, tmp_path, "Costco", "KS ALMND BTR", "Kirkland Almond Butter", 11.49
    )
    store = db.query(Store).filter_by(name="Costco").first()
    pasted = Receipt(store_id=store.id, status="completed", image_path=None)
    db.add(pasted)
    db.commit()
    db.add(
        OcrCorrection(
            receipt_id=pasted.id,
            store_id=store.id,
            field="name",
            ai_value="PASTED LINE",
            approved_value="Pasted Line",
        )
    )
    db.commit()

    block = harness.build_prompt_extra(db, photo, "global")

    assert "KS ALMND BTR" in block
    assert "PASTED LINE" not in block, "a pasted-text correction reached a photo receipt's prompt"
