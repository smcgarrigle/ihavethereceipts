"""CM-13: the backfill checker has to actually catch things.

A check that silently stops checking looks exactly like a check that passes,
and this one guards the backfill every later ticket keys off. So each test
breaks one invariant and asserts a failure is reported — the clean case alone
would prove nothing.

The script lives in scripts/ rather than the app package, so it is loaded by
path the same way test_correction_keys_and_overrides.py loads the migration.
"""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import TestingSessionLocal

from app.models import CorrectionOverride, CorrectionUsage, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_correction_backfill.py"


@pytest.fixture(scope="module")
def checker():
    spec = importlib.util.spec_from_file_location("cm13_checker", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixtures that build rows without saving, where a check takes plain data
# ---------------------------------------------------------------------------


def _correction(
    receipt_id=1,
    store_id=1,
    field="name",
    input_type="image",
    ai_value="MLK WHL GAL",
    approved_value="Whole Milk",
    key=...,
    row_id=1,
):
    row = OcrCorrection(
        receipt_id=receipt_id,
        store_id=store_id,
        field=field,
        input_type=input_type,
        ai_value=ai_value,
        approved_value=approved_value,
    )
    row.id = row_id
    if key is not ...:
        row.content_key = key
    elif input_type is None:
        # content_key() has no defence against a null input type, and this
        # helper is used to build rows that are deliberately malformed.
        row.content_key = "0" * 40
    else:
        row.content_key = content_key(store_id, input_type, field, ai_value, approved_value)
    return row


def _receipt_stub(receipt_id=1, image_path="/data/uploads/a.jpg"):
    receipt = Receipt(status="completed", image_path=image_path)
    receipt.id = receipt_id
    return receipt


# ---------------------------------------------------------------------------
# Content keys
# ---------------------------------------------------------------------------


def test_a_reproducible_key_passes(checker):
    check = checker.check_content_keys([_correction()])

    assert check.passed
    assert check.counted == 1


def test_a_missing_key_is_caught(checker):
    check = checker.check_content_keys([_correction(key=None)])

    assert not check.passed
    assert "no content_key" in check.failures[0]


def test_a_short_key_is_caught(checker):
    check = checker.check_content_keys([_correction(key="abc123")])

    assert not check.passed
    assert "6-character key" in check.failures[0]


def test_a_key_that_does_not_recompute_is_caught(checker):
    """The real hazard: the migration's frozen copy drifting from the app's."""
    check = checker.check_content_keys([_correction(key="0" * 40)])

    assert not check.passed
    assert "hash to" in check.failures[0]


def test_a_key_computed_from_other_values_is_caught(checker):
    """A key that is valid for a different lesson is still wrong for this one."""
    wrong = content_key(1, "image", "name", "SOMETHING", "Else")
    check = checker.check_content_keys([_correction(key=wrong)])

    assert not check.passed


# ---------------------------------------------------------------------------
# Input types
# ---------------------------------------------------------------------------


def test_a_matching_input_type_passes(checker):
    receipts = {1: _receipt_stub()}

    check = checker.check_input_types([_correction()], receipts)

    assert check.passed


def test_a_missing_input_type_is_caught(checker):
    receipts = {1: _receipt_stub()}

    check = checker.check_input_types([_correction(input_type=None)], receipts)

    assert not check.passed
    assert "no input_type" in check.failures[0]


def test_an_unknown_input_type_is_caught(checker):
    receipts = {1: _receipt_stub()}

    check = checker.check_input_types([_correction(input_type="fax")], receipts)

    assert not check.passed
    assert "'fax'" in check.failures[0]


def test_an_input_type_that_contradicts_its_receipt_is_caught(checker):
    """Says image, but the receipt is a PDF — this is what drift looks like."""
    receipts = {1: _receipt_stub(image_path="/data/uploads/a.pdf")}

    check = checker.check_input_types([_correction(input_type="image")], receipts)

    assert not check.passed
    assert "but receipt 1 is 'pdf'" in check.failures[0]


def test_a_paste_correction_matches_a_receipt_with_no_file(checker):
    receipts = {1: _receipt_stub(image_path=None)}

    check = checker.check_input_types([_correction(input_type="paste")], receipts)

    assert check.passed


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


def test_a_present_receipt_passes(checker):
    check = checker.check_receipts_exist([_correction()], {1: _receipt_stub()})

    assert check.passed


def test_a_missing_receipt_is_caught(checker):
    check = checker.check_receipts_exist([_correction(receipt_id=99)], {1: _receipt_stub()})

    assert not check.passed
    assert "missing receipt 99" in check.failures[0]


# ---------------------------------------------------------------------------
# Stores: reported, never failed
# ---------------------------------------------------------------------------


def test_a_null_store_is_reported_not_failed(checker):
    """An unidentified receipt legitimately has no store."""
    check = checker.check_stores([_correction(store_id=None)])

    assert check.passed
    assert "1 correction(s) have no store" in check.detail


def test_stores_present_leaves_the_detail_alone(checker):
    check = checker.check_stores([_correction()])

    assert check.passed
    assert "have no store" not in check.detail


# ---------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------


def _store_row(db, name="Costco"):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _saved_receipt(db, store, image_path="/data/uploads/a.jpg"):
    receipt = Receipt(status="completed", store_id=store.id, image_path=image_path)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _saved_correction(db, receipt):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field="name",
        input_type="image",
        ai_value="MLK WHL GAL",
        approved_value="Whole Milk",
        content_key=content_key(receipt.store_id, "image", "name", "MLK WHL GAL", "Whole Milk"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_usage_against_a_known_key_passes(checker, db):
    receipt = _saved_receipt(db, _store_row(db))
    correction = _saved_correction(db, receipt)
    db.add(
        CorrectionUsage(
            content_key=correction.content_key,
            receipt_id=receipt.id,
            used_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.commit()

    check = checker.check_usage_not_fabricated(db, [correction], {receipt.id: receipt})

    assert check.passed
    assert check.counted == 1


def test_usage_naming_an_unknown_key_is_caught(checker, db):
    """A fabricated usage row: no correction or override carries this key."""
    receipt = _saved_receipt(db, _store_row(db))
    correction = _saved_correction(db, receipt)
    db.add(
        CorrectionUsage(
            content_key="f" * 40,
            receipt_id=receipt.id,
            used_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.commit()

    check = checker.check_usage_not_fabricated(db, [correction], {receipt.id: receipt})

    assert not check.passed
    assert "which no correction or override carries" in check.failures[0]


def test_usage_pointing_at_a_missing_receipt_is_caught(checker, db):
    receipt = _saved_receipt(db, _store_row(db))
    correction = _saved_correction(db, receipt)
    db.add(
        CorrectionUsage(
            content_key=correction.content_key,
            receipt_id=receipt.id,
            used_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.commit()

    # The receipt exists in the database but not in the map handed to the check.
    check = checker.check_usage_not_fabricated(db, [correction], {})

    assert not check.passed
    assert "missing receipt" in check.failures[0]


def test_usage_against_an_override_key_passes(checker, db):
    """An override outlives its correction row, so its key is still known."""
    receipt = _saved_receipt(db, _store_row(db))
    key = content_key(receipt.store_id, "image", "name", "GONE", "Gone")
    db.add(CorrectionOverride(content_key=key, input_type="image", field="name", suppressed=True))
    db.add(
        CorrectionUsage(
            content_key=key,
            receipt_id=receipt.id,
            used_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    db.commit()

    check = checker.check_usage_not_fabricated(db, [], {receipt.id: receipt})

    assert check.passed


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def test_a_well_formed_override_passes(checker, db):
    db.add(
        CorrectionOverride(
            content_key=content_key(1, "image", "name", "A", "B"),
            input_type="image",
            field="name",
        )
    )
    db.commit()

    check = checker.check_overrides(db)

    assert check.passed
    assert check.counted == 1


def test_an_override_with_a_bad_key_is_caught(checker, db):
    db.add(CorrectionOverride(content_key="short", input_type="image", field="name"))
    db.commit()

    check = checker.check_overrides(db)

    assert not check.passed
    assert "'short'" in check.failures[0]


def test_an_override_with_an_unknown_input_type_is_caught(checker, db):
    db.add(
        CorrectionOverride(
            content_key=content_key(1, "image", "name", "A", "B"),
            input_type="fax",
            field="name",
        )
    )
    db.commit()

    check = checker.check_overrides(db)

    assert not check.passed
    assert "'fax'" in check.failures[0]


# ---------------------------------------------------------------------------
# Reporting and exit status
# ---------------------------------------------------------------------------


def test_failures_are_truncated_without_verbose(checker, capsys):
    check = checker.Check("many failures")
    for i in range(10):
        check.fail(f"problem {i}")

    check.report(limit=3, verbose=False)
    printed = capsys.readouterr().out

    assert "problem 2" in printed
    assert "problem 3" not in printed
    assert "and 7 more" in printed


def test_verbose_lists_everything(checker, capsys):
    check = checker.Check("many failures")
    for i in range(10):
        check.fail(f"problem {i}")

    check.report(limit=3, verbose=True)
    printed = capsys.readouterr().out

    assert "problem 9" in printed
    assert "more (use --verbose)" not in printed


def test_a_passing_check_is_marked_ok(checker, capsys):
    checker.Check("fine").report(limit=5, verbose=False)

    assert "[ok  ]" in capsys.readouterr().out


def test_a_failing_check_is_marked_fail(checker, capsys):
    check = checker.Check("not fine")
    check.fail("something")
    check.report(limit=5, verbose=False)

    assert "[FAIL]" in capsys.readouterr().out


def test_main_exits_zero_on_a_clean_database(checker, db, capsys):
    receipt = _saved_receipt(db, _store_row(db))
    _saved_correction(db, receipt)
    db.commit()
    db.close()

    with (
        patch.object(checker, "SessionLocal", TestingSessionLocal),
        patch("sys.argv", ["check_correction_backfill.py"]),
    ):
        code = checker.main()

    assert code == 0
    assert "All 6 checks passed." in capsys.readouterr().out


def test_main_exits_one_when_a_check_fails(checker, db, capsys):
    """A malformed override is enough to fail the run."""
    receipt = _saved_receipt(db, _store_row(db))
    _saved_correction(db, receipt)
    db.add(CorrectionOverride(content_key="short", input_type="image", field="name"))
    db.commit()
    db.close()

    with (
        patch.object(checker, "SessionLocal", TestingSessionLocal),
        patch("sys.argv", ["check_correction_backfill.py"]),
    ):
        code = checker.main()

    printed = capsys.readouterr().out
    assert code == 1
    assert "1 of 6 checks failed." in printed
