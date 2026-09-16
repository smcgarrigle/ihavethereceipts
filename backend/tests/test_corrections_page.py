"""CM-10: the Settings → Corrections page.

Every lesson the OCR prompt can draw on, one row per distinct correction, with
how often it was recorded and when it was last sent. Read-only: removing,
pinning and editing arrive with CM-11.

Correction text comes off receipts via a model, so it is untrusted and the
page must escape it — the same class of bug as test_fragment_html_escaping.py,
which is why the payloads below are shared with that file.
"""

from datetime import UTC, datetime, timedelta

import pytest
from bs4 import BeautifulSoup

from app.models import CorrectionUsage, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import list_corrections, set_pinned, set_suppressed

ATTR_BREAKOUT = '"><img src=x onerror=alert(1)>'
JS_BREAKOUT = "');alert(1);//"

PAGE = "/settings/corrections"


def _naive(moment: datetime) -> datetime:
    """correction_usage.used_at is a naive DateTime column."""
    return moment.replace(tzinfo=None)


def _store(db, name="Costco"):
    store = db.query(Store).filter_by(name=name).first()
    if not store:
        store = Store(name=name)
        db.add(store)
        db.commit()
    return store


def _receipt(db, store, image_path="/data/uploads/a.jpg"):
    receipt = Receipt(status="completed", store_id=store.id, image_path=image_path)
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def _lesson(
    db,
    receipt,
    ai_value="MLK WHL GAL",
    approved_value="Whole Milk",
    field="name",
    input_type="image",
    minutes_ago=0,
    item_context=None,
    quantity=None,
):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field=field,
        input_type=input_type,
        ai_value=ai_value,
        approved_value=approved_value,
        item_context=item_context,
        quantity=quantity,
        content_key=content_key(receipt.store_id, input_type, field, ai_value, approved_value),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _used(db, correction, receipt, days_ago=0):
    db.add(
        CorrectionUsage(
            content_key=correction.content_key,
            correction_id=correction.id,
            receipt_id=receipt.id,
            used_at=_naive(datetime.now(UTC) - timedelta(days=days_ago)),
        )
    )
    db.commit()


def _rows(body):
    soup = BeautifulSoup(body, "html.parser")
    table = soup.find(id="corrections-table")
    assert table is not None, "the page rendered without its corrections table"
    return table.find("tbody").find_all("tr")


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def test_the_page_renders(client, db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt)

    response = client.get(PAGE)

    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    assert soup.find(id="corrections-table") is not None
    assert soup.find(id="corrections-tally") is not None
    assert soup.find(id="filter-store") is not None
    assert soup.find(id="filter-input-type") is not None


def test_a_lesson_appears_with_its_values(client, db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt)

    body = client.get(PAGE).text

    assert "MLK WHL GAL" in body
    assert "Whole Milk" in body
    assert "Costco" in body


def test_the_empty_state_says_so(client):
    body = client.get(PAGE).text

    assert len(_rows(body)) == 1
    assert "No corrections recorded yet" in body


def test_the_page_is_reachable_from_settings(client):
    body = client.get("/settings").text

    assert PAGE in body, "the settings page has no link to the corrections page"


# ---------------------------------------------------------------------------
# One row per distinct lesson
# ---------------------------------------------------------------------------


def test_the_same_lesson_on_several_receipts_is_one_row(client, db):
    store = _store(db)
    for i in range(3):
        _lesson(db, _receipt(db, store, f"/data/uploads/{i}.jpg"), minutes_ago=i)

    rows = _rows(client.get(PAGE).text)

    assert len(rows) == 1
    assert "3" in rows[0].find_all("td")[3].get_text()


def test_different_lessons_get_their_own_rows(client, db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")
    _lesson(db, receipt, "ORG SPNCH", "Organic Spinach", minutes_ago=5)

    assert len(_rows(client.get(PAGE).text)) == 2


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_filtering_by_store(client, db):
    costco = _store(db)
    safeway = _store(db, "Safeway")
    _lesson(db, _receipt(db, costco), "COSTCO LINE", "Costco Line")
    _lesson(db, _receipt(db, safeway, "/data/uploads/s.jpg"), "SFWY LINE", "Safeway Line")

    body = client.get(PAGE, params={"store": "Safeway"}).text

    assert "Safeway Line" in body
    assert "Costco Line" not in body


def test_filtering_by_input_type(client, db):
    store = _store(db)
    _lesson(db, _receipt(db, store), "IMAGE LINE", "Image Line")
    _lesson(db, _receipt(db, store, None), "PASTE LINE", "Paste Line", input_type="paste")

    body = client.get(PAGE, params={"input_type": "paste"}).text

    assert "Paste Line" in body
    assert "Image Line" not in body


def test_a_filter_matching_nothing_says_so(client, db):
    store = _store(db)
    _lesson(db, _receipt(db, store, None), "PASTE LINE", "Paste Line", input_type="paste")

    body = client.get(PAGE, params={"store": "Costco", "input_type": "image"}).text

    assert len(_rows(body)) == 1
    assert "No corrections match this filter" in body


def test_an_unknown_input_type_shows_everything(client, db):
    """A stale bookmark should not be a 422."""
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt)

    response = client.get(PAGE, params={"input_type": "fax"})

    assert response.status_code == 200
    assert "Whole Milk" in response.text


def test_the_store_list_offers_every_store(client, db):
    _store(db)
    _store(db, "Safeway")

    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")
    options = [o.get("value") for o in soup.find(id="filter-store").find_all("option")]

    assert "" in options and "Costco" in options and "Safeway" in options


# ---------------------------------------------------------------------------
# Usage columns
# ---------------------------------------------------------------------------


def test_an_unused_lesson_reads_never(client, db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt)

    cells = _rows(client.get(PAGE).text)[0].find_all("td")

    assert cells[4].get_text(strip=True) == "0"
    assert cells[5].get_text(strip=True) == "never"


def test_usage_this_week_is_counted(client, db):
    store = _store(db)
    receipt = _receipt(db, store)
    target = _receipt(db, store, "/data/uploads/b.jpg")
    lesson = _lesson(db, receipt)
    _used(db, lesson, target, days_ago=1)
    _used(db, lesson, target, days_ago=2)

    cells = _rows(client.get(PAGE).text)[0].find_all("td")

    assert cells[4].get_text(strip=True) == "2"
    assert cells[5].get_text(strip=True) != "never"


def test_usage_older_than_a_week_is_not_counted_as_this_week(db):
    store = _store(db)
    receipt = _receipt(db, store)
    target = _receipt(db, store, "/data/uploads/b.jpg")
    lesson = _lesson(db, receipt)
    _used(db, lesson, target, days_ago=30)

    rows = list_corrections(db)

    assert rows[0]["used_this_week"] == 0
    assert rows[0]["used_total"] == 1
    assert rows[0]["last_used"] is not None


def test_the_busiest_lesson_sorts_first(client, db):
    store = _store(db)
    receipt = _receipt(db, store)
    target = _receipt(db, store, "/data/uploads/b.jpg")
    quiet = _lesson(db, receipt, "QUIET", "Quiet Lesson")
    busy = _lesson(db, receipt, "BUSY", "Busy Lesson", minutes_ago=5)
    _used(db, busy, target, days_ago=1)

    rows = _rows(client.get(PAGE).text)

    assert "Busy Lesson" in rows[0].get_text()
    assert "Quiet Lesson" in rows[1].get_text()
    assert quiet.content_key != busy.content_key


# ---------------------------------------------------------------------------
# Decisions already recorded
# ---------------------------------------------------------------------------


def test_a_removed_lesson_is_marked(client, db):
    receipt = _receipt(db, _store(db))
    set_suppressed(db, _lesson(db, receipt))

    body = client.get(PAGE).text

    assert "removed" in body


def test_a_pinned_lesson_is_marked(client, db):
    receipt = _receipt(db, _store(db))
    set_pinned(db, _lesson(db, receipt))

    body = client.get(PAGE).text

    assert "pinned" in body


def test_a_price_line_shows_its_quantity(client, db):
    receipt = _receipt(db, _store(db))
    _lesson(
        db,
        receipt,
        "4.34",
        "8.68",
        field="price",
        item_context="Sparkling Water",
        quantity=2.0,
    )

    body = client.get(PAGE).text

    assert "a line of 2" in body
    assert "Sparkling Water" in body


# ---------------------------------------------------------------------------
# Correction text is untrusted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [ATTR_BREAKOUT, JS_BREAKOUT], ids=["attr", "js"])
def test_the_page_escapes_correction_values(client, db, payload):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt, f"AI {payload}", f"Approved {payload}", item_context=f"Item {payload}")

    body = client.get(PAGE).text

    assert payload not in body, (
        "the corrections page emitted a model-derived value verbatim — correction "
        "text comes off receipts and can break out of its HTML context"
    )


@pytest.mark.parametrize("payload", [ATTR_BREAKOUT, JS_BREAKOUT], ids=["attr", "js"])
def test_the_page_escapes_store_names(client, db, payload):
    """The store name is typed freely in review and lands in a select option."""
    store = _store(db, f"Mart {payload}")
    _lesson(db, _receipt(db, store))

    body = client.get(PAGE).text

    assert payload not in body, "the corrections page emitted a store name verbatim"


@pytest.mark.parametrize("payload", [ATTR_BREAKOUT, JS_BREAKOUT], ids=["attr", "js"])
def test_the_filter_echo_escapes_the_requested_store(client, payload):
    """The chosen store is echoed back into the form from the query string."""
    body = client.get(PAGE, params={"store": payload}).text

    assert payload not in body, "the corrections page echoed a query parameter verbatim"


# ---------------------------------------------------------------------------
# The aggregation itself
# ---------------------------------------------------------------------------


def test_list_corrections_rejects_an_unknown_input_type(db):
    with pytest.raises(ValueError):
        list_corrections(db, input_type="fax")


def test_list_corrections_counts_rows_not_lessons(db):
    store = _store(db)
    for i in range(4):
        _lesson(db, _receipt(db, store, f"/data/uploads/{i}.jpg"), minutes_ago=i)

    rows = list_corrections(db)

    assert len(rows) == 1
    assert rows[0]["seen"] == 4


def test_list_corrections_reports_the_store_and_input_type(db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt)

    row = list_corrections(db)[0]

    assert row["store"] == "Costco"
    assert row["input_type"] == "image"
    assert row["field"] == "name"
