"""CRV added on the review page is its own line, not carved out of the item.

The review form keeps an item's Total Line Price fixed and derives the
original price as total + discounts - fees. A $0.30 CRV fee added to a $9.99
six-pack therefore dropped the beer to $9.69 and saved the line at $9.99: the
CRV never reached the receipt total. CRV found by OCR was already moved into
the CRV section as its own row; one added by hand now gets the same treatment.

Runs the real static/js/receipt_review.js in node with a stub document.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "static" / "js" / "receipt_review.js"

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const [scriptPath, ocrJson, steps] = process.argv.slice(1);
const elements = {
    'ocr-data': { textContent: ocrJson },
    'categories-data': { textContent: '[]' },
};
const context = { document: { getElementById: id => elements[id] || null, title: '' }, console };
vm.createContext(context);
vm.runInContext(fs.readFileSync(scriptPath, 'utf8'), context);
const review = vm.runInContext('receiptReview', context)({ receiptId: 1, csrfToken: 't' });
review.init();
const item = review.items[0];
for (const step of JSON.parse(steps)) {
    if (step.op === 'addFee') item.fees.push({ amount: 0, description: '', type: 'other' });
    if (step.op === 'set') { item.fees[step.fee][step.field] = step.value; review.updateBasePrice(item); }
    if (step.op === 'change') review.moveCrvFee(item, item.fees[step.fee]);
}
console.log(JSON.stringify({
    item: { final_price: item.final_price, base_price: item.base_price, fees: item.fees },
    crv: review.crv_items.map(r => ({ name: r.name, final_price: r.final_price })),
    saved_total: [...review.items, ...review.crv_items]
        .reduce((sum, r) => sum + Number(r.final_price), 0).toFixed(2),
    status: review.crvStatus,
}));
"""


def _beer(**overrides):
    item = {
        "name": "Athletic Brewing Free Wave Non-Alcoholic Hazy IPA",
        "base_price": 9.99,
        "final_price": 9.99,
        "quantity": 1,
        "discounts": [],
        "fees": [],
        "category": "Beverages",
    }
    item.update(overrides)
    return {"store_name": "Test", "items": [item]}


def _run(ocr: dict, steps: list[dict]) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    result = subprocess.run(
        [node, "-e", HARNESS, str(SCRIPT), json.dumps(ocr), json.dumps(steps)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return dict(json.loads(result.stdout))


# Amount typed first, then the type switched to CRV (the order in the bug report).
TYPE_AFTER_AMOUNT = [
    {"op": "addFee"},
    {"op": "set", "fee": 0, "field": "amount", "value": ".30"},
    {"op": "change", "fee": 0},
    {"op": "set", "fee": 0, "field": "type", "value": "crv"},
    {"op": "change", "fee": 0},
]


def test_crv_added_in_review_becomes_its_own_line():
    out = _run(_beer(), TYPE_AFTER_AMOUNT)

    assert out["item"] == {"final_price": "9.99", "base_price": "9.99", "fees": []}
    assert out["crv"] == [{"name": "CRV Fee", "final_price": "0.30"}]
    assert out["saved_total"] == "10.29"
    assert "0.30" in out["status"]


def test_crv_typed_into_the_description_also_moves():
    out = _run(
        _beer(),
        [
            {"op": "addFee"},
            {"op": "set", "fee": 0, "field": "amount", "value": "0.30"},
            {"op": "set", "fee": 0, "field": "description", "value": "CRV"},
            {"op": "change", "fee": 0},
        ],
    )

    assert out["crv"] == [{"name": "CRV", "final_price": "0.30"}]
    assert out["saved_total"] == "10.29"


def test_a_crv_fee_without_an_amount_stays_until_one_is_entered():
    # Picking CRV before typing the amount must not move an empty $0 row.
    out = _run(
        _beer(),
        [
            {"op": "addFee"},
            {"op": "set", "fee": 0, "field": "type", "value": "crv"},
            {"op": "change", "fee": 0},
        ],
    )

    assert out["crv"] == []
    assert len(out["item"]["fees"]) == 1


def test_other_fees_stay_on_the_item():
    out = _run(
        _beer(),
        [
            {"op": "addFee"},
            {"op": "set", "fee": 0, "field": "amount", "value": "0.10"},
            {"op": "set", "fee": 0, "field": "type", "value": "deposit"},
            {"op": "change", "fee": 0},
        ],
    )

    assert out["crv"] == []
    assert out["item"]["base_price"] == "9.89"  # unchanged behaviour for non-CRV fees
    assert out["saved_total"] == "9.99"


def test_crv_found_by_ocr_is_still_split_out_of_the_item():
    # OCR's final_price includes the CRV, so loading takes it back out.
    out = _run(
        _beer(final_price=10.29, fees=[{"amount": 0.30, "type": "crv", "description": "CRV"}]),
        [],
    )

    assert out["item"]["final_price"] == "9.99"
    assert out["crv"] == [{"name": "CRV", "final_price": "0.30"}]
    assert out["saved_total"] == "10.29"
