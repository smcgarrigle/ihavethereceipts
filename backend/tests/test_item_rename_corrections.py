"""CM-20: renaming an item in the item editor records name lessons.

A rename is a person saying what an item is called. Until now it changed the
label only: the model kept reading the old text, and the next receipt's line
failed to match the renamed item and created a duplicate.

The lesson must name what the model read, not the item's old name. On the live
database 19% of purchase lines were matched to their item from different
receipt text, so several tests use receipt text that differs from the item name.
"""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup

from app.models import CorrectionOverride, CorrectionUsage, Item, OcrCorrection, Receipt, Store
from app.models.receipt import ReceiptItem
from app.services import correction_service
from app.services.correction_keys import content_key
from app.services.correction_service import (
    RENAME_SOURCE,
    get_correction_prompt,
    list_corrections,
    record_corrections,
    record_rename_corrections,
    suppressed_keys,
)


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


def _bought(db, store, lines, image_path="/data/uploads/a.jpg", ocr=True, produce=False):
    """A receipt at ``store``. ``lines`` is [(item, text the model read, price)]."""
    data = {
        "items": [{"name": read, "final_price": price, "quantity": 1} for _, read, price in lines]
    }
    if produce:
        data["produce_mode"] = True
    receipt = Receipt(
        status="completed",
        store_id=store.id,
        image_path=image_path,
        ocr_data=json.dumps(data) if ocr else None,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    for item, _, price in lines:
        db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, price=price, quantity=1))
    db.commit()
    db.refresh(receipt)
    return receipt


def _rename(db, item, new_name):
    old = item.name
    item.name = new_name
    item.normalized_name = new_name.lower()
    db.commit()
    return record_rename_corrections(db, item, old, new_name)


def _rename_rows(db, item=None):
    query = db.query(OcrCorrection).filter(OcrCorrection.source == RENAME_SOURCE)
    if item is not None:
        query = query.filter(OcrCorrection.item_id == item.id)
    return query.all()


def _review_lesson(db, receipt, ai_value, approved_value, input_type="image"):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field="name",
        input_type=input_type,
        ai_value=ai_value,
        approved_value=approved_value,
        content_key=content_key(receipt.store_id, input_type, "name", ai_value, approved_value),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# What the lesson says
# ---------------------------------------------------------------------------


def test_a_rename_becomes_a_name_lesson(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])

    result = _rename(db, chips, "Potato Chips")

    assert result == {"lessons": 1, "superseded": 0}
    [row] = _rename_rows(db, chips)
    assert (row.field, row.ai_value, row.approved_value) == ("name", "Chips", "Potato Chips")
    assert row.store_id == costco.id
    assert row.input_type == "image"


def test_the_lesson_names_what_the_model_read_not_the_old_item_name(db):
    """The receipt said KTL CHPS SEA SLT; the item was fuzzy-matched as Chips."""
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "KTL CHPS SEA SLT", 3.99)])

    _rename(db, chips, "Kettle Chips Sea Salt")

    [row] = _rename_rows(db, chips)
    assert row.ai_value == "KTL CHPS SEA SLT"
    assert row.approved_value == "Kettle Chips Sea Salt"


def test_the_lesson_reaches_the_next_prompt_for_that_store(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])

    _rename(db, chips, "Potato Chips")

    block = get_correction_prompt(db, store_name="Costco", input_type="image")
    assert "'Chips' was corrected to 'Potato Chips'" in block


def test_only_the_renamed_items_line_becomes_a_lesson(db):
    costco = _store(db)
    chips, milk, eggs = _item(db, "Chips"), _item(db, "Milk"), _item(db, "Eggs")
    _bought(db, costco, [(milk, "MLK WHL", 4.49), (chips, "CHP", 3.99), (eggs, "EGG LRG", 5.29)])

    _rename(db, chips, "Potato Chips")

    rows = _rename_rows(db)
    assert [(r.ai_value, r.approved_value) for r in rows] == [("CHP", "Potato Chips")]


def test_each_store_gets_its_own_lesson(db):
    costco, safeway = _store(db, "Costco"), _store(db, "Safeway")
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "KS CHIPS", 3.99)])
    _bought(db, safeway, [(chips, "SW CHIPS", 2.99)])

    result = _rename(db, chips, "Potato Chips")

    assert result["lessons"] == 2
    by_store = {r.store_id: r.ai_value for r in _rename_rows(db, chips)}
    assert by_store == {costco.id: "KS CHIPS", safeway.id: "SW CHIPS"}


@pytest.mark.parametrize(
    ("image_path", "kind"),
    [("/data/uploads/a.jpg", "image"), ("/data/uploads/a.pdf", "pdf"), (None, "paste")],
)
def test_the_lesson_takes_the_receipts_input_type(db, image_path, kind):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)], image_path=image_path)

    _rename(db, chips, "Potato Chips")

    [row] = _rename_rows(db, chips)
    assert row.input_type == kind


def test_text_far_from_the_item_name_is_paired_by_price(db):
    """After a merge the receipt text can share nothing with the item's name."""
    costco = _store(db)
    chips, milk = _item(db, "Chips"), _item(db, "Milk")
    _bought(db, costco, [(milk, "MILK", 4.49), (chips, "KTL CHPS SEA SLT", 3.99)])

    _rename(db, chips, "Kettle Chips Sea Salt")

    assert [r.ai_value for r in _rename_rows(db, chips)] == ["KTL CHPS SEA SLT"]


def test_two_leftover_lines_at_the_same_price_are_not_guessed_between(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    receipt = _bought(db, costco, [(chips, "KTL CHPS SEA SLT", 3.99)])
    data = json.loads(receipt.ocr_data)
    data["items"].append({"name": "ZQX 44 BRKN", "final_price": 3.99, "quantity": 1})
    receipt.ocr_data = json.dumps(data)
    db.commit()

    assert _rename(db, chips, "Kettle Chips Sea Salt")["lessons"] == 0


def test_one_row_per_receipt_so_a_receipt_never_gets_its_own_answer(db):
    """The eval excludes a receipt's own corrections; a rename row is one of them."""
    costco = _store(db)
    chips = _item(db, "Chips")
    first = _bought(db, costco, [(chips, "Chips", 3.99)])
    second = _bought(db, costco, [(chips, "Chips", 3.99)])

    result = _rename(db, chips, "Potato Chips")

    assert result["lessons"] == 1  # one distinct lesson
    assert sorted(r.receipt_id for r in _rename_rows(db, chips)) == sorted([first.id, second.id])
    both = get_correction_prompt(
        db, store_name="Costco", input_type="image", exclude_receipt_ids=[first.id, second.id]
    )
    assert "Potato Chips" not in both


# ---------------------------------------------------------------------------
# What is not recorded
# ---------------------------------------------------------------------------


def test_a_change_of_case_records_nothing(db):
    """The receipt text differs from both names, so only the rename check can stop it."""
    costco = _store(db)
    chips = _item(db, "potato chips")
    receipt = _bought(db, costco, [(chips, "PTO CHPS", 3.99)])
    review = _review_lesson(db, receipt, "PTO CHPS", "potato chips")

    assert _rename(db, chips, "Potato Chips") == {"lessons": 0, "superseded": 0}
    assert _rename_rows(db) == []
    assert review.content_key not in suppressed_keys(db)


def test_text_the_model_already_reads_as_the_new_name_records_nothing(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Potato Chips", 3.99)])

    assert _rename(db, chips, "Potato Chips")["lessons"] == 0


@pytest.mark.parametrize("kind", ["no extraction", "produce mode"])
def test_receipts_without_a_model_extraction_are_skipped(db, kind):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(
        db,
        costco,
        [(chips, "Chips", 3.99)],
        ocr=kind != "no extraction",
        produce=kind == "produce mode",
    )

    assert _rename(db, chips, "Potato Chips")["lessons"] == 0


def test_a_removed_lesson_is_not_written_again(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])
    key = content_key(costco.id, "image", "name", "Chips", "Potato Chips")
    db.add(
        CorrectionOverride(
            content_key=key,
            store_id=costco.id,
            input_type="image",
            field="name",
            ai_value="Chips",
            approved_value="Potato Chips",
            suppressed=True,
        )
    )
    db.commit()

    assert _rename(db, chips, "Potato Chips")["lessons"] == 0


# ---------------------------------------------------------------------------
# Living alongside review lessons
# ---------------------------------------------------------------------------


def test_saving_the_review_again_keeps_rename_lessons(db):
    """Review saves delete and re-record their receipt's lessons; not these."""
    costco = _store(db)
    chips = _item(db, "Chips")
    receipt = _bought(db, costco, [(chips, "Chips", 3.99)])
    _rename(db, chips, "Potato Chips")

    reviewed = [SimpleNamespace(name="Potato Chips", final_price=3.99, quantity=1)]
    record_corrections(db, receipt, reviewed)
    db.commit()

    assert len(_rename_rows(db, chips)) == 1


def test_saving_the_review_still_replaces_its_own_review_lessons(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    receipt = _bought(db, costco, [(chips, "Chips", 3.99)])
    _review_lesson(db, receipt, "Chips", "Old Review Name")

    record_corrections(db, receipt, [SimpleNamespace(name="Chips", final_price=3.99, quantity=1)])
    db.commit()

    stale = db.query(OcrCorrection).filter_by(approved_value="Old Review Name").all()
    assert stale == []


def test_a_second_rename_replaces_the_first(db):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])
    _rename(db, chips, "Potato Chips")

    _rename(db, chips, "Kettle Chips")

    rows = _rename_rows(db, chips)
    assert [(r.ai_value, r.approved_value) for r in rows] == [("Chips", "Kettle Chips")]


def test_a_review_lesson_pointing_at_the_old_name_is_removed(db):
    """CHP -> Chips and CHP -> Potato Chips in one prompt would contradict."""
    costco = _store(db)
    chips = _item(db, "Chips")
    receipt = _bought(db, costco, [(chips, "CHP", 3.99)])
    stale = _review_lesson(db, receipt, "CHP", "Chips")

    result = _rename(db, chips, "Potato Chips")

    assert result["superseded"] == 1
    assert stale.content_key in suppressed_keys(db)
    block = get_correction_prompt(db, store_name="Costco", input_type="image")
    assert "'CHP' was corrected to 'Potato Chips'" in block
    assert "'CHP' was corrected to 'Chips'" not in block


def test_unrelated_review_lessons_are_left_alone(db):
    costco, safeway = _store(db, "Costco"), _store(db, "Safeway")
    chips = _item(db, "Chips")
    receipt = _bought(db, costco, [(chips, "CHP", 3.99)])
    other_text = _review_lesson(db, receipt, "CHIPZ", "Chips")
    other_target = _review_lesson(db, receipt, "CHP", "Corn Chips")
    elsewhere = _review_lesson(
        db, _bought(db, safeway, [(_item(db, "Salsa"), "SLSA", 4.0)]), "CHP", "Chips"
    )

    _rename(db, chips, "Potato Chips")

    kept = suppressed_keys(db)
    for row in (other_text, other_target, elsewhere):
        assert row.content_key not in kept


# ---------------------------------------------------------------------------
# Corrections page
# ---------------------------------------------------------------------------


def test_the_corrections_page_marks_rename_lessons(db, client):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])
    _rename(db, chips, "Potato Chips")

    [row] = list_corrections(db)
    assert row["from_item_editor"] is True

    soup = BeautifulSoup(client.get("/settings/corrections").text, "html.parser")
    assert "from item editor" in soup.get_text()


def test_a_rename_after_use_is_not_counted_as_a_recurrence(db):
    """Recurrence means the model got it wrong again on review. A rename is not that."""
    costco = _store(db)
    chips = _item(db, "Chips")
    receipt = _bought(db, costco, [(chips, "Chips", 3.99)])
    review = _review_lesson(db, receipt, "Chips", "Potato Chips")
    review.created_at = datetime.now(UTC) - timedelta(days=3)
    db.add(
        CorrectionUsage(
            content_key=review.content_key,
            receipt_id=receipt.id,
            used_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    db.commit()

    # Same lesson, recorded now by the rename, after it was first sent.
    _rename(db, chips, "Potato Chips")
    assert _rename_rows(db, chips)[0].content_key == review.content_key

    [row] = list_corrections(db)
    assert row["seen"] == 2
    assert row["recurred"] == 0


def test_a_real_recurrence_is_still_counted_alongside_a_rename(db):
    """Rows are read newest first, so the rename row here is not the first one."""
    costco = _store(db)
    chips = _item(db, "Chips")
    receipt = _bought(db, costco, [(chips, "Chips", 3.99)])
    first = _review_lesson(db, receipt, "Chips", "Potato Chips")
    first.created_at = datetime.now(UTC) - timedelta(days=3)
    db.add(
        CorrectionUsage(
            content_key=first.content_key,
            receipt_id=receipt.id,
            used_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    db.commit()
    _rename(db, chips, "Potato Chips")
    for row in _rename_rows(db, chips):
        row.created_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()
    # The model got it wrong again on a later receipt, after the lesson was sent.
    _review_lesson(db, _bought(db, costco, [(chips, "Chips", 3.99)]), "Chips", "Potato Chips")

    [row] = list_corrections(db)
    assert row["seen"] == 3
    assert row["recurred"] == 1


# ---------------------------------------------------------------------------
# Item editor
# ---------------------------------------------------------------------------


def test_renaming_through_the_item_editor_records_the_lesson(db, client):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])

    response = client.put(f"/api/items/{chips.id}", json={"name": "Potato Chips"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["lessons"] == 1
    db.refresh(chips)
    assert chips.name == "Potato Chips"
    assert len(_rename_rows(db, chips)) == 1


def test_a_category_change_records_nothing(db, client):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])

    body = client.put(f"/api/items/{chips.id}", json={"category_id": None}).json()

    assert body["lessons"] == 0
    assert _rename_rows(db) == []


def test_saving_the_same_name_records_nothing(db, client):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "CHP", 3.99)])

    body = client.put(f"/api/items/{chips.id}", json={"name": "Chips"}).json()

    assert body["lessons"] == 0


def test_a_failure_recording_lessons_does_not_undo_the_rename(db, client, monkeypatch):
    costco = _store(db)
    chips = _item(db, "Chips")
    _bought(db, costco, [(chips, "Chips", 3.99)])

    def broken(*_args, **_kwargs):
        raise RuntimeError("pairing failed")

    monkeypatch.setattr(correction_service, "_pair_items", broken)

    response = client.put(f"/api/items/{chips.id}", json={"name": "Potato Chips"})

    assert response.status_code == 200
    assert response.json()["lessons"] == 0
    db.refresh(chips)
    assert chips.name == "Potato Chips"
    assert _rename_rows(db) == []


def test_the_name_field_says_a_rename_adds_a_correction(db, client):
    chips = _item(db, "Chips")

    soup = BeautifulSoup(client.get(f"/items/{chips.id}/insights").text, "html.parser")

    field = soup.find("input", id="insight-item-name")
    hint = soup.find(id=field["aria-describedby"])
    assert hint is not None
    assert "adds a correction" in hint.get_text()
    assert hint.find("a", href="/settings/corrections") is not None
