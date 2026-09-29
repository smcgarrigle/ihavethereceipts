"""CM-21: permanent per-store names.

The prompt's correction block holds ten lessons and forgets: a lesson the model
follows is never recorded again, so it ages out. This table does not: text a
store printed before names the item it was last saved as, after extraction, on
every receipt, with no prompt space.
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import TestingSessionLocal

from app.models import Item, MergeLog, Receipt, ReceiptItem, Store, StoreItemAlias
from app.services import store_names
from app.services.store_names import item_for, remember_receipt, text_key

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _store(db, name="Costco"):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _item(db, name):
    item = Item(name=name, normalized_name=name.lower().strip())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _saved(db, store, lines, ocr=True, produce=False):
    """A reviewed receipt. ``lines`` is [(item, text the model returned, price)]."""
    data = {
        "items": [{"name": read, "final_price": price, "quantity": 1} for _, read, price in lines]
    }
    if produce:
        data["produce_mode"] = True
    receipt = Receipt(
        status="completed",
        store_id=store.id,
        image_path="/data/uploads/a.jpg",
        ocr_data=json.dumps(data) if ocr else None,
    )
    db.add(receipt)
    db.commit()
    for item, _, price in lines:
        db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, price=price, quantity=1))
    db.commit()
    db.refresh(receipt)
    return receipt


def _remember(db, receipt):
    written = remember_receipt(db, receipt)
    db.commit()
    return written


def _alias(db, store, text):
    return (
        db.query(StoreItemAlias).filter_by(store_id=store.id, text_key=text_key(text)).one_or_none()
    )


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_text_key_ignores_case_and_spacing():
    assert text_key("  KS   Org  EGGS ") == "ks org eggs"


def test_a_line_names_the_item_it_was_saved_as(db):
    costco = _store(db)
    chips = _item(db, "Salt & Vinegar Potato Chips")
    _remember(db, _saved(db, costco, [(chips, "CHIPS", 3.99)]))

    assert item_for(db, costco.id, "chips").id == chips.id


def test_names_belong_to_one_store(db):
    costco, safeway = _store(db, "Costco"), _store(db, "Safeway")
    chips = _item(db, "Potato Chips")
    _remember(db, _saved(db, costco, [(chips, "CHIPS", 3.99)]))

    assert item_for(db, safeway.id, "CHIPS") is None


@pytest.mark.parametrize("text", ["", None, "NEVER PRINTED"])
def test_unknown_text_finds_nothing(db, text):
    costco = _store(db)
    _remember(db, _saved(db, costco, [(_item(db, "Chips"), "CHIPS", 3.99)]))

    assert item_for(db, costco.id, text) is None


def test_no_store_finds_nothing(db):
    costco = _store(db)
    _remember(db, _saved(db, costco, [(_item(db, "Chips"), "CHIPS", 3.99)]))

    assert item_for(db, None, "CHIPS") is None


def test_a_deleted_item_finds_nothing(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    _remember(db, _saved(db, costco, [(chips, "CHIPS", 3.99)]))
    db.query(ReceiptItem).filter_by(item_id=chips.id).delete()
    db.delete(chips)
    db.commit()

    assert item_for(db, costco.id, "CHIPS") is None


def test_a_failed_lookup_finds_nothing_rather_than_raising(db):
    costco = _store(db)
    with patch.object(db, "query", side_effect=RuntimeError("database gone")):
        assert item_for(db, costco.id, "CHIPS") is None


def test_a_rename_needs_no_bookkeeping(db):
    """The name points at the item, so the item's current name is what comes back."""
    costco = _store(db)
    chips = _item(db, "Chips")
    _remember(db, _saved(db, costco, [(chips, "CHIPS", 3.99)]))

    chips.name = "Salt & Vinegar Potato Chips"
    db.commit()

    assert item_for(db, costco.id, "CHIPS").name == "Salt & Vinegar Potato Chips"


# ---------------------------------------------------------------------------
# Remembering
# ---------------------------------------------------------------------------


def test_the_models_own_reading_is_the_key_not_the_catalog_name(db):
    """Auto-merge renames the stored line and keeps the reading in original_ocr_name."""
    costco = _store(db)
    chips = _item(db, "Potato Chips")
    receipt = _saved(db, costco, [(chips, "Potato Chips", 3.99)])
    data = json.loads(receipt.ocr_data)
    data["items"][0]["original_ocr_name"] = "PTO CHPS"
    receipt.ocr_data = json.dumps(data)
    db.commit()

    _remember(db, receipt)

    assert _alias(db, costco, "PTO CHPS").item_id == chips.id
    assert _alias(db, costco, "Potato Chips") is None


def test_the_latest_save_wins(db):
    """Replayed on the live corpus, latest-wins beat a majority vote."""
    costco = _store(db)
    old, new = _item(db, "ADVIL"), _item(db, "Advil Ibuprofen 200 mg")
    for _ in range(3):
        _remember(db, _saved(db, costco, [(old, "ADVIL", 9.99)]))
    _remember(db, _saved(db, costco, [(new, "ADVIL", 9.99)]))

    assert item_for(db, costco.id, "ADVIL").id == new.id
    assert db.query(StoreItemAlias).count() == 1


def test_every_saved_line_is_remembered(db):
    costco = _store(db)
    milk, eggs = _item(db, "Whole Milk"), _item(db, "Organic Eggs")

    written = _remember(db, _saved(db, costco, [(milk, "MLK WHL", 4.49), (eggs, "ORG EGGS", 8.99)]))

    assert written == 2
    assert item_for(db, costco.id, "MLK WHL").id == milk.id
    assert item_for(db, costco.id, "ORG EGGS").id == eggs.id


def test_text_far_from_the_item_name_is_paired_by_price(db):
    costco = _store(db)
    chips, milk = _item(db, "Chips"), _item(db, "Milk")

    _remember(db, _saved(db, costco, [(milk, "MILK", 4.49), (chips, "KTL CHPS SEA SLT", 3.99)]))

    assert item_for(db, costco.id, "KTL CHPS SEA SLT").id == chips.id


@pytest.mark.parametrize("kind", ["no extraction", "produce mode"])
def test_receipts_without_a_model_reading_are_skipped(db, kind):
    costco = _store(db)
    receipt = _saved(
        db,
        costco,
        [(_item(db, "Chips"), "CHIPS", 3.99)],
        ocr=kind != "no extraction",
        produce=kind == "produce mode",
    )

    assert _remember(db, receipt) == 0
    assert db.query(StoreItemAlias).count() == 0


def test_a_failure_while_remembering_does_not_raise(db, monkeypatch):
    costco = _store(db)
    receipt = _saved(db, costco, [(_item(db, "Chips"), "CHIPS", 3.99)])

    def broken(*_args, **_kwargs):
        raise RuntimeError("pairing failed")

    monkeypatch.setattr("app.services.correction_service.pair_receipt_lines", broken)

    assert remember_receipt(db, receipt) == 0


# ---------------------------------------------------------------------------
# Where names are read and written
# ---------------------------------------------------------------------------


def _review_body(name, price):
    return {
        "items": [
            {
                "name": name,
                "base_price": price,
                "quantity": 1,
                "discounts": [],
                "fees": [],
                "final_price": price,
                "category": "",
            }
        ]
    }


def test_saving_a_review_remembers_its_lines(db, client):
    costco = _store(db)
    receipt = Receipt(
        store_id=costco.id,
        status="review",
        image_path="/data/uploads/a.jpg",
        ocr_data=json.dumps({"items": [{"name": "CHIPS", "final_price": 3.99, "quantity": 1}]}),
    )
    db.add(receipt)
    db.commit()

    response = client.post(
        f"/api/receipts/{receipt.id}/save-reviewed-items",
        json=_review_body("Salt & Vinegar Potato Chips", 3.99),
    )

    assert response.json()["success"] is True
    found = item_for(db, costco.id, "CHIPS")
    assert found is not None and found.name == "Salt & Vinegar Potato Chips"


def test_the_review_page_proposes_the_remembered_item(db, client):
    """Chips scores 31 against this name, far below the review page's 90."""
    costco = _store(db)
    chips = _item(db, "Salt & Vinegar Potato Chips")
    _remember(db, _saved(db, costco, [(chips, "CHIPS", 3.99)]))
    pending = Receipt(
        store_id=costco.id,
        status="review",
        total_amount=3.99,
        ocr_data=json.dumps({"items": [{"name": "CHIPS", "final_price": 3.99}]}),
    )
    db.add(pending)
    db.commit()

    text = client.get(f"/receipts/{pending.id}/review").text

    # The page embeds the lines with tojson, which escapes & as \u0026.
    assert '"name": "Salt \\u0026 Vinegar Potato Chips"' in text
    assert '"original_ocr_name": "CHIPS"' in text


def test_the_review_page_without_a_name_falls_back_to_name_matching(db, client):
    costco = _store(db)
    _item(db, "Salt & Vinegar Potato Chips")
    pending = Receipt(
        store_id=costco.id,
        status="review",
        total_amount=3.99,
        ocr_data=json.dumps({"items": [{"name": "CHIPS", "final_price": 3.99}]}),
    )
    db.add(pending)
    db.commit()

    text = client.get(f"/receipts/{pending.id}/review").text

    assert '"name": "CHIPS"' in text


def _release(session):
    session.commit()
    session.close()


def _ocr_run(db, task, ocr_function, image_path, item_text):
    """Run an OCR task with the model stubbed; return the stored extraction."""
    costco = _store(db)
    chips = _item(db, "Salt & Vinegar Potato Chips")
    _remember(db, _saved(db, costco, [(chips, "CHIPS", 3.99)]))
    pending = Receipt(store_id=costco.id, status="pending", image_path=image_path, total_amount=0.0)
    db.add(pending)
    db.commit()
    receipt_id = pending.id
    _release(db)

    result = {
        "store_name": "Costco",
        "total_amount": 3.99,
        "items": [{"name": item_text, "final_price": 3.99, "quantity": 1}],
    }
    from app.services import ocr

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch(f"app.services.ocr.{ocr_function}", return_value=result),
        patch("app.services.category_tagger.categorize_items_batch", return_value={}),
    ):
        if task == "paste":
            ocr.process_text_receipt_task(receipt_id, "CHIPS 3.99")
        else:
            ocr.process_receipt_task(receipt_id, image_path)

    check = TestingSessionLocal()
    try:
        stored = check.get(Receipt, receipt_id).ocr_data
    finally:
        check.close()
    return json.loads(stored)["items"][0]


@pytest.mark.parametrize(
    ("task", "ocr_function", "image_path"),
    [
        ("upload", "process_receipt_image", "/tmp/cm21-image.jpg"),
        ("paste", "process_text_receipt", None),
    ],
)
def test_ocr_names_a_line_this_store_printed_before(db, task, ocr_function, image_path):
    line = _ocr_run(db, task, ocr_function, image_path, "CHIPS")

    assert line["name"] == "Salt & Vinegar Potato Chips"
    assert line["original_ocr_name"] == "CHIPS"


def test_the_eval_still_scores_the_models_own_reading(db):
    """ocr_eval scores original_ocr_name, so the table can never be credited to the model."""
    spec = importlib.util.spec_from_file_location("ocr_eval", SCRIPTS / "ocr_eval.py")
    assert spec and spec.loader
    ocr_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ocr_eval)

    line = _ocr_run(db, "upload", "process_receipt_image", "/tmp/cm21-eval.jpg", "CHIPS")

    assert ocr_eval.ai_name(line) == "CHIPS"


# ---------------------------------------------------------------------------
# Merges
# ---------------------------------------------------------------------------


def test_a_merge_moves_names_to_the_kept_item(db, client):
    costco = _store(db)
    short, full = _item(db, "ADVIL"), _item(db, "Advil Ibuprofen 200 mg")
    _remember(db, _saved(db, costco, [(short, "ADVIL", 9.99)]))

    client.post("/api/items/merge", json={"keep_item_id": full.id, "merge_item_ids": [short.id]})

    assert item_for(db, costco.id, "ADVIL").id == full.id


def test_undoing_a_merge_moves_the_names_back(db, client):
    costco = _store(db)
    short, full = _item(db, "ADVIL"), _item(db, "Advil Ibuprofen 200 mg")
    _remember(db, _saved(db, costco, [(short, "ADVIL", 9.99)]))
    client.post("/api/items/merge", json={"keep_item_id": full.id, "merge_item_ids": [short.id]})

    client.post("/api/items/merge/undo")

    restored = item_for(db, costco.id, "ADVIL")
    assert restored.name == "ADVIL"
    assert restored.id != full.id


def test_undo_leaves_a_name_that_a_later_save_moved(db, client):
    costco = _store(db)
    short, full, other = _item(db, "ADVIL"), _item(db, "Advil Ibuprofen"), _item(db, "Motrin")
    _remember(db, _saved(db, costco, [(short, "ADVIL", 9.99)]))
    client.post("/api/items/merge", json={"keep_item_id": full.id, "merge_item_ids": [short.id]})
    _remember(db, _saved(db, costco, [(other, "ADVIL", 9.99)]))

    client.post("/api/items/merge/undo")

    assert item_for(db, costco.id, "ADVIL").id == other.id


def test_undoing_a_merge_logged_before_store_names_moves_nothing(db, client):
    costco = _store(db)
    full = _item(db, "Advil Ibuprofen")
    db.add(MergeLog(target_item_id=full.id, source_item_name="ADVIL", receipt_item_ids="[]"))
    db.commit()

    response = client.post("/api/items/merge/undo")

    assert response.status_code == 200
    assert item_for(db, costco.id, "ADVIL") is None


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------


@pytest.fixture
def backfill_script():
    spec = importlib.util.spec_from_file_location(
        "backfill_store_names", SCRIPTS / "backfill_store_names.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_backfill_replays_in_upload_order(db, backfill_script):
    costco = _store(db)
    old, new = _item(db, "ADVIL"), _item(db, "Advil Ibuprofen 200 mg")
    _saved(db, costco, [(old, "ADVIL", 9.99)])
    _saved(db, costco, [(new, "ADVIL", 9.99)])

    report = backfill_script.backfill(db)
    db.commit()

    assert report["receipts_used"] == 2
    assert report["names"] == 1
    assert item_for(db, costco.id, "ADVIL").id == new.id
    assert _alias(db, costco, "ADVIL").source == store_names.BACKFILL_SOURCE


def test_the_backfill_writes_nothing_without_apply(db, backfill_script, monkeypatch, capsys):
    costco = _store(db)
    _saved(db, costco, [(_item(db, "Chips"), "CHIPS", 3.99)])
    monkeypatch.setattr(backfill_script, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr("sys.argv", ["backfill_store_names.py"])
    _release(db)

    assert backfill_script.main() == 0

    check = TestingSessionLocal()
    try:
        assert check.query(StoreItemAlias).count() == 0
    finally:
        check.close()
    assert "Preview only" in capsys.readouterr().out
