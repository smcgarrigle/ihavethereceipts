"""CM-02: corrections are scoped to the input type they came from.

The block was filtered by store only, so lessons from pasted receipt text went
into prompts for photographed receipts and the reverse. On the live database
123 of the first 433 corrections came from pasted text, including price lines
from an iHerb table (Price column read instead of Subtotal) that taught image
prompts to double prices.
"""

from unittest.mock import patch

import pytest
from conftest import TestingSessionLocal

from app.models import OcrCorrection, Receipt, Store
from app.services.correction_service import get_correction_prompt, input_type_of


def _store(db, name):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _receipt(db, store, image_path):
    receipt = Receipt(store_id=store.id, status="completed", image_path=image_path)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _name_fix(db, receipt, ai_value, approved_value):
    db.add(
        OcrCorrection(
            receipt_id=receipt.id,
            store_id=receipt.store_id,
            field="name",
            ai_value=ai_value,
            approved_value=approved_value,
        )
    )
    db.commit()


@pytest.fixture
def mixed(db):
    """One correction from each input type, all at the same store."""
    costco = _store(db, "Costco")
    photo = _receipt(db, costco, "/data/uploads/a.jpg")
    pdf = _receipt(db, costco, "/data/uploads/b.PDF")
    paste = _receipt(db, costco, None)
    _name_fix(db, photo, "PHOTO LINE", "Photo Line")
    _name_fix(db, pdf, "PDF LINE", "Pdf Line")
    _name_fix(db, paste, "PASTE LINE", "Paste Line")
    return {"image": photo, "pdf": pdf, "paste": paste}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/data/uploads/a.jpg", "image"),
        ("/data/uploads/a.png", "image"),
        ("/data/uploads/a.pdf", "pdf"),
        ("/data/uploads/a.PDF", "pdf"),
        (None, "paste"),
        ("", "paste"),
    ],
)
def test_input_type_of(path, expected):
    assert input_type_of(path) == expected


@pytest.mark.parametrize(
    ("input_type", "kept", "left_out"),
    [
        ("image", "PHOTO LINE", ("PDF LINE", "PASTE LINE")),
        ("pdf", "PDF LINE", ("PHOTO LINE", "PASTE LINE")),
        ("paste", "PASTE LINE", ("PHOTO LINE", "PDF LINE")),
    ],
)
@pytest.mark.usefixtures("mixed")
def test_each_input_type_gets_only_its_own_corrections(db, input_type, kept, left_out):
    block = get_correction_prompt(db, input_type=input_type)
    assert kept in block
    for other in left_out:
        assert other not in block, (
            f"a {input_type} prompt carried a correction from another input type"
        )


@pytest.mark.usefixtures("mixed")
def test_store_fallback_stays_within_the_input_type(db):
    """A store with no photo corrections falls back to all stores' photos, not its own pastes."""
    iherb = _store(db, "Iherb")
    _name_fix(db, _receipt(db, iherb, None), "IHERB PASTE", "iHerb Paste")

    block = get_correction_prompt(db, store_name="Iherb", input_type="image")

    assert "all stores" in block
    assert "PHOTO LINE" in block
    assert "IHERB PASTE" not in block and "PASTE LINE" not in block


@pytest.mark.usefixtures("mixed")
def test_store_scope_applies_inside_the_input_type(db):
    safeway = _store(db, "Safeway")
    _name_fix(db, _receipt(db, safeway, "/data/uploads/s.jpg"), "SFWY PHOTO", "Safeway Photo")

    block = get_correction_prompt(db, store_name="Safeway", input_type="image")

    assert "Safeway" in block and "SFWY PHOTO" in block
    assert "PHOTO LINE" not in block, "store scope should drop other stores' photo corrections"


@pytest.mark.usefixtures("mixed")
def test_the_block_names_its_source(db):
    assert "of pasted receipt text at all stores" in get_correction_prompt(db, input_type="paste")
    assert "of photographed receipts" in get_correction_prompt(db, input_type="image")


@pytest.mark.usefixtures("mixed")
def test_no_input_type_keeps_every_correction_and_the_old_wording(db):
    block = get_correction_prompt(db)
    assert all(line in block for line in ("PHOTO LINE", "PDF LINE", "PASTE LINE"))
    assert "past human reviews at all stores" in block


def test_exclusion_still_applies_with_an_input_type(db, mixed):
    block = get_correction_prompt(db, input_type="image", exclude_receipt_ids=[mixed["image"].id])
    assert block == "", "the only photo correction was excluded, so no block should be built"


def test_unknown_input_type_is_rejected(db):
    with pytest.raises(ValueError):
        get_correction_prompt(db, input_type="fax")


# ---------------------------------------------------------------------------
# The OCR tasks must pass the input type. The filter above is only useful if
# production actually asks for it.
# ---------------------------------------------------------------------------


def _release(session):
    """Commit and close so the task's own session can BEGIN on the shared connection."""
    session.commit()
    session.close()


def _pending(db, image_path):
    store = _store(db, "Wiring Store")
    receipt = Receipt(store_id=store.id, status="pending", image_path=image_path, total_amount=0.0)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt.id


@pytest.mark.parametrize(
    ("image_path", "ocr_function", "expected"),
    [
        ("/tmp/cm02-photo.jpg", "process_receipt_image", "image"),
        ("/tmp/cm02-order.pdf", "process_pdf_receipt", "pdf"),
    ],
)
def test_upload_task_asks_for_its_own_input_type(db, image_path, ocr_function, expected):
    receipt_id = _pending(db, image_path)
    _release(db)

    from app.services.ocr import process_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch("app.services.correction_service.get_correction_prompt", return_value="") as build,
        patch(f"app.services.ocr.{ocr_function}", return_value={"error": "stopped in test"}),
    ):
        process_receipt_task(receipt_id, image_path)

    assert build.called, "the task never built a corrections block"
    assert build.call_args.kwargs.get("input_type") == expected


def test_paste_task_asks_for_pasted_corrections(db):
    receipt_id = _pending(db, None)
    _release(db)

    from app.services.ocr import process_text_receipt_task

    with (
        patch("app.database.SessionLocal", TestingSessionLocal),
        patch("app.services.correction_service.get_correction_prompt", return_value="") as build,
        patch("app.services.ocr.process_text_receipt", return_value={"error": "stopped in test"}),
    ):
        process_text_receipt_task(receipt_id, "Milk 4.29")

    assert build.called, "the paste task never built a corrections block"
    assert build.call_args.kwargs.get("input_type") == "paste"
