"""CM-15: the eval set checker has to catch a set that will not run.

The check runs on the machine that runs the model, before hours of OCR start.
A check that passes a set with a missing image or a PDF would waste the whole
run, so each test breaks one thing and asserts it is reported.
"""

import importlib.util
import json
from pathlib import Path

import pytest

from app.models import Receipt, Store
from app.models.receipt import ReceiptItem

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "eval_sets" / "select_cm15_set.py"


@pytest.fixture(scope="module")
def selector():
    spec = importlib.util.spec_from_file_location("cm15_selector", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _receipt(db, image_path, items=5, ocr_items=True):
    store = db.query(Store).filter_by(name="Costco").first()
    if not store:
        store = Store(name="Costco")
        db.add(store)
        db.commit()
    receipt = Receipt(
        store_id=store.id,
        status="completed",
        image_path=image_path,
        ocr_data=json.dumps({"items": [{"name": "A"}] if ocr_items else []}),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    for _ in range(items):
        db.add(ReceiptItem(receipt_id=receipt.id, quantity=1, price=1.0))
    db.commit()
    return receipt


def _list(tmp_path, ids):
    path = tmp_path / "set.txt"
    path.write_text("# header\n# Costco\n" + "\n".join(str(i) for i in ids) + "\n")
    return path


def test_ids_ignore_comments_and_blank_lines(selector, tmp_path):
    path = tmp_path / "set.txt"
    path.write_text("# a comment\n\n12\n  # indented comment\n34\n")

    assert selector.read_ids(path) == [12, 34]


def test_a_usable_set_passes(selector, db, tmp_path, capsys):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x")
    receipt = _receipt(db, str(image))

    code = selector.check(db, _list(tmp_path, [receipt.id]))

    assert code == 0
    assert "every image is on disk" in capsys.readouterr().out


def test_a_missing_image_is_caught(selector, db, tmp_path, capsys):
    """The Mac trap: the path is valid on one machine and not the other."""
    receipt = _receipt(db, "/home/nobody/not-here.jpg")

    code = selector.check(db, _list(tmp_path, [receipt.id]))

    assert code == 1
    assert "image not found" in capsys.readouterr().out


def test_a_pdf_is_caught(selector, db, tmp_path, capsys):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"x")
    receipt = _receipt(db, str(pdf))

    code = selector.check(db, _list(tmp_path, [receipt.id]))

    assert code == 1
    assert "not an image receipt" in capsys.readouterr().out


def test_an_unscoreable_receipt_is_caught(selector, db, tmp_path, capsys):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x")
    receipt = _receipt(db, str(image), ocr_items=False)

    code = selector.check(db, _list(tmp_path, [receipt.id]))

    assert code == 1
    assert "not scoreable" in capsys.readouterr().out


def test_an_unknown_id_is_caught(selector, db, tmp_path, capsys):
    code = selector.check(db, _list(tmp_path, [999999]))

    assert code == 1
    assert "not in this database" in capsys.readouterr().out


def test_duplicate_ids_are_caught(selector, db, tmp_path, capsys):
    image = tmp_path / "a.jpg"
    image.write_bytes(b"x")
    receipt = _receipt(db, str(image))

    code = selector.check(db, _list(tmp_path, [receipt.id, receipt.id]))

    assert code == 1
    assert "duplicate" in capsys.readouterr().out


def test_the_frozen_set_has_thirty_distinct_ids(selector):
    ids = selector.read_ids(selector.DEFAULT_OUTPUT)

    assert len(ids) == 30
    assert len(set(ids)) == 30
