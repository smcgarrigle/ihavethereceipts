"""Audit finding 18: spreadsheet formula injection in the CSV/XLSX export.

Item, store and category names went straight into a DataFrame and out through
`to_csv` / `to_excel` with no formula-prefix guard, so a receipt line beginning
with `=` is evaluated when the export is opened in Excel or LibreOffice. Those
names come from OCR of a receipt image.

It needs the user to export and then open the file, which is why the audit
rates it low — but it is the one finding that leaves the browser entirely. The
CSP and the HTML escaping have no say in what a spreadsheet does with a
downloaded file.
"""

from __future__ import annotations

import datetime
import io

import pandas as pd
import pytest

from app.api.export import _formula_safe, _safe_frame
from app.models import Category, Item, Receipt, ReceiptItem, Store

PAYLOADS = [
    "=1+1",
    "=cmd|'/c calc'!A1",
    '=HYPERLINK("http://evil.example","click")',
    "+1+1",
    "-1+1",
    "@SUM(A1:A9)",
    "\t=1+1",
    " =1+1",  # spreadsheets strip leading whitespace before deciding
]


class TestFormulaSafe:
    @pytest.mark.parametrize("payload", PAYLOADS)
    def test_dangerous_leaders_are_prefixed(self, payload):
        assert _formula_safe(payload).startswith("'")
        assert payload in _formula_safe(payload)

    @pytest.mark.parametrize(
        "value",
        ["Milk", "Mary's Gone Crackers", "365 WFM 2% MILK", "Ben & Jerry's", "", "Trader Joe's"],
    )
    def test_ordinary_names_are_untouched(self, value):
        assert _formula_safe(value) == value

    @pytest.mark.parametrize("value", [None, 1, -5.0, 0, 3.14])
    def test_non_text_is_untouched(self, value):
        assert _formula_safe(value) == value


class TestSafeFrame:
    def test_it_actually_runs_on_this_pandas(self):
        """pandas 3 infers StringDtype, so `dtype == object` matches nothing.

        The first version of this guard used that idiom and silently did
        nothing at all.
        """
        frame = _safe_frame([{"Item": "=1+1"}])
        assert frame["Item"][0] == "'=1+1"

    def test_numeric_columns_stay_numeric(self):
        """A negative price is a number, not a quoted string."""
        frame = _safe_frame([{"Item": "Milk", "Price": -5.0, "Quantity": 2.0}])
        assert frame["Price"].dtype == "float64"
        assert "-5.0" in frame.to_csv(index=False)
        assert "'-5.0" not in frame.to_csv(index=False)

    def test_missing_values_survive(self):
        frame = _safe_frame([{"Item": "Milk", "Weight": None, "FDC ID": ""}])
        assert frame["Item"][0] == "Milk"


@pytest.fixture
def hostile_receipt(db):
    category = Category(name="=1+1")
    store = Store(name='=HYPERLINK("http://evil.example","click")')
    db.add_all([category, store])
    db.commit()
    item = Item(name="=cmd|'/c calc'!A1", normalized_name="calc", category_id=category.id)
    db.add(item)
    db.commit()
    receipt = Receipt(
        store_id=store.id,
        status="completed",
        total_amount=5.0,
        purchase_date=datetime.datetime(2026, 9, 8),
    )
    db.add(receipt)
    db.commit()
    db.add(ReceiptItem(receipt_id=receipt.id, item_id=item.id, quantity=1, price=5.0))
    db.commit()
    return receipt


class TestTheEndpoints:
    @pytest.mark.parametrize("url", ["/api/export/all/csv", "/api/export/receipt/{id}/csv"])
    def test_csv_exports_are_inert(self, client, hostile_receipt, url):
        resp = client.get(url.format(id=hostile_receipt.id))
        assert resp.status_code == 200
        body = resp.text

        for cell in ("=cmd|'/c calc'!A1", "=1+1", "=HYPERLINK"):
            assert cell in body, "the value went missing entirely"
        # Every occurrence of a formula leader must be quoted first.
        for line in body.splitlines()[1:]:
            for field in line.split(","):
                stripped = field.strip('"')
                assert not stripped.startswith(("=", "@")), f"unquoted formula: {field!r}"

    @pytest.mark.parametrize("url", ["/api/export/all/excel", "/api/export/receipt/{id}/excel"])
    def test_excel_exports_are_inert(self, client, hostile_receipt, url):
        resp = client.get(url.format(id=hostile_receipt.id))
        assert resp.status_code == 200

        frame = pd.read_excel(io.BytesIO(resp.content))
        for column in ("Store", "Item", "Category"):
            value = str(frame[column][0])
            assert value.startswith("'"), f"{column} was written as a live formula: {value!r}"

    def test_an_ordinary_receipt_exports_unchanged(self, client, db):
        store = Store(name="Trader Joe's")
        category = Category(name="Dairy")
        db.add_all([store, category])
        db.commit()
        item = Item(name="Whole Milk", normalized_name="whole milk", category_id=category.id)
        db.add(item)
        db.commit()
        r = Receipt(
            store_id=store.id,
            status="completed",
            total_amount=4.99,
            purchase_date=datetime.datetime(2026, 9, 8),
        )
        db.add(r)
        db.commit()
        db.add(ReceiptItem(receipt_id=r.id, item_id=item.id, quantity=1, price=4.99))
        db.commit()

        body = client.get("/api/export/all/csv").text
        assert "Trader Joe's" in body
        assert "Whole Milk" in body
        assert "'" + "Trader" not in body, "a harmless name was quoted"
