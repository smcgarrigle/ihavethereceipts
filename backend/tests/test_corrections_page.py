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
from app.services.correction_service import (
    correction_distribution,
    list_corrections,
    set_pinned,
    set_suppressed,
)

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
    # Each section is its own tbody with a heading row; lessons carry the marker.
    return table.select("tr[data-lesson]")


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

    assert not _rows(body)
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

    assert not _rows(body)
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

    rows = _rows(client.get(PAGE, params={"show": "all"}).text)

    assert len(rows) == 1
    assert "removed" in rows[0].get_text()


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


# ---------------------------------------------------------------------------
# Sections: what the person did, in plain words
# ---------------------------------------------------------------------------


def _sections(body):
    table = BeautifulSoup(body, "html.parser").find(id="corrections-table")
    return {
        tbody["data-group"]: tbody for tbody in table.find_all("tbody") if tbody.get("data-group")
    }


def test_lessons_are_grouped_by_what_was_done(client, db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt, "MLK WHL GAL", "Whole Milk")
    _lesson(db, receipt, "4.34", "8.68", field="price", item_context="Whole Milk")
    _lesson(db, receipt, "2", "3", field="quantity", item_context="Bananas")
    _lesson(db, receipt, None, "Organic Spinach", field="item_missed")
    _lesson(db, receipt, "SUBTOTAL", None, field="item_hallucinated")

    sections = _sections(client.get(PAGE).text)

    assert list(sections) == ["name", "price", "missed", "made_up"]
    assert "Names you fixed" in sections["name"].get_text()
    assert "Lines the model missed" in sections["missed"].get_text()
    assert "Lines the model made up" in sections["made_up"].get_text()
    # A quantity fix sits with prices: both are a number on a line.
    assert len(sections["price"].select("tr[data-lesson]")) == 2


def test_a_section_with_nothing_in_it_is_left_out(client, db):
    _lesson(db, _receipt(db, _store(db)))

    assert list(_sections(client.get(PAGE).text)) == ["name"]


def test_a_missed_line_shows_only_what_was_added(client, db):
    _lesson(db, _receipt(db, _store(db)), None, "Organic Spinach", field="item_missed")

    text = _rows(client.get(PAGE).text)[0].get_text()

    assert "Organic Spinach" in text
    assert "(missing)" not in text


def test_a_made_up_line_shows_only_what_was_deleted(client, db):
    _lesson(db, _receipt(db, _store(db)), "SUBTOTAL", None, field="item_hallucinated")

    text = _rows(client.get(PAGE).text)[0].get_text()

    assert "SUBTOTAL" in text
    assert "(removed)" not in text


# ---------------------------------------------------------------------------
# In use, or all
# ---------------------------------------------------------------------------


def _many(db, receipt, count):
    """``count`` distinct lessons, the first the newest."""
    return [_lesson(db, receipt, f"READ {i}", f"Saved {i}", minutes_ago=i) for i in range(count)]


def test_only_lessons_the_next_prompt_would_carry_are_listed(client, db, monkeypatch):
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "2")
    _many(db, _receipt(db, _store(db)), 5)

    text = " ".join(row.get_text() for row in _rows(client.get(PAGE).text))

    assert "Saved 0" in text and "Saved 1" in text
    assert "Saved 2" not in text


def test_all_lists_the_older_lessons_and_marks_them(client, db, monkeypatch):
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "2")
    _many(db, _receipt(db, _store(db)), 5)

    rows = _rows(client.get(PAGE, params={"show": "all"}).text)

    assert len(rows) == 5
    assert sum("no longer sent" in row.get_text() for row in rows) == 3


def test_the_view_links_carry_both_counts(client, db, monkeypatch):
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "2")
    _many(db, _receipt(db, _store(db)), 5)

    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")

    assert "(2)" in soup.find(id="view-in-use").get_text()
    assert "(5)" in soup.find(id="view-all").get_text()
    assert soup.find(id="view-in-use").get("aria-current") == "page"
    assert "show=all" in soup.find(id="view-all")["href"]


def test_the_view_links_keep_the_filter(client, db):
    _lesson(db, _receipt(db, _store(db)))

    soup = BeautifulSoup(
        client.get(PAGE, params={"store": "Costco", "input_type": "image"}).text, "html.parser"
    )

    href = soup.find(id="view-all")["href"]
    assert "store=Costco" in href and "input_type=image" in href


def test_a_pinned_old_lesson_is_in_use(client, db, monkeypatch):
    monkeypatch.setenv("CORRECTION_PROMPT_LIMIT", "2")
    lessons = _many(db, _receipt(db, _store(db)), 5)
    set_pinned(db, lessons[-1])

    text = " ".join(row.get_text() for row in _rows(client.get(PAGE).text))

    assert "Saved 4" in text


def test_a_removed_lesson_is_not_in_use(client, db):
    set_suppressed(db, _lesson(db, _receipt(db, _store(db))))

    assert not _rows(client.get(PAGE).text)
    assert "Show all 1" in client.get(PAGE).text


def test_row_actions_post_back_with_the_view_and_filter(client, db):
    _lesson(db, _receipt(db, _store(db)))

    soup = BeautifulSoup(
        client.get(PAGE, params={"show": "all", "store": "Costco"}).text, "html.parser"
    )

    targets = [b["hx-post"] for b in soup.find_all("button") if b.get("hx-post")]
    assert targets
    for target in targets:
        assert "show=all" in target and "store=Costco" in target


# ---------------------------------------------------------------------------
# The chart and the table under it
# ---------------------------------------------------------------------------


def test_the_distribution_counts_rows_by_kind(db):
    store = _store(db)
    first, second = _receipt(db, store), _receipt(db, store, "/data/uploads/b.jpg")
    _lesson(db, first, "MLK WHL GAL", "Whole Milk")
    _lesson(db, second, "MLK WHL GAL", "Whole Milk")
    _lesson(db, first, "4.34", "8.68", field="price", item_context="Whole Milk")
    _lesson(db, first, None, "Organic Spinach", field="item_missed")
    _lesson(db, first, "SUBTOTAL", None, field="item_hallucinated")

    found = correction_distribution(db)

    assert found["totals"] == {"name": 2, "price": 1, "missed": 1, "made_up": 1}
    assert found["total"] == 5
    assert found["receipts"] == 2


def test_the_distribution_leaves_out_deposit_lines(db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt, None, "CRV", field="item_missed")

    assert correction_distribution(db)["total"] == 0


def test_the_distribution_bins_are_contiguous(db):
    store = _store(db)
    first = _receipt(db, store)
    far = Receipt(id=first.id + 60, status="completed", store_id=store.id, image_path="/x.jpg")
    db.add(far)
    db.commit()
    _lesson(db, first)
    _lesson(db, far, "ORG SPNCH", "Organic Spinach")

    bins = correction_distribution(db)["bins"]

    assert [b["name"] for b in bins] == [1, 0, 1]
    assert bins[0]["label"] == "0\u201324"


def test_the_distribution_splits_by_how_the_receipt_came_in(db):
    store = _store(db)
    _lesson(db, _receipt(db, store, "/data/uploads/a.jpg"))
    _lesson(db, _receipt(db, store, "/data/uploads/a.pdf"), "ORG SPNCH", "Organic Spinach")
    _lesson(db, _receipt(db, store, None), "PASTE LINE", "Paste Line")

    sources = correction_distribution(db)["sources"]

    assert [s["input_type"] for s in sources] == ["image", "pdf", "paste"]
    assert all(s["receipts"] == 1 and s["name"] == 1 for s in sources)


def test_the_distribution_follows_the_filters(db):
    costco, safeway = _store(db), _store(db, "Safeway")
    _lesson(db, _receipt(db, costco))
    _lesson(db, _receipt(db, safeway, "/data/uploads/a.pdf"), "ORG SPNCH", "Organic Spinach")

    assert correction_distribution(db, store_name="Costco")["total"] == 1
    assert correction_distribution(db, input_type="pdf")["total"] == 1


def test_the_distribution_rejects_an_unknown_input_type(db):
    with pytest.raises(ValueError):
        correction_distribution(db, input_type="fax")


def test_the_page_shows_totals_chart_and_source_table(client, db):
    receipt = _receipt(db, _store(db))
    _lesson(db, receipt)
    _lesson(db, receipt, None, "Organic Spinach", field="item_missed")

    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")

    assert soup.select_one('[data-total="name"]').get_text(strip=True) == "1"
    assert soup.select_one('[data-total="missed"]').get_text(strip=True) == "1"
    assert soup.select_one('[data-total="made_up"]').get_text(strip=True) == "0"
    assert soup.find("canvas", id="correctionsChart") is not None
    source_rows = soup.find(id="corrections-by-source").find("tbody").find_all("tr")
    assert [row.find("th").get_text(strip=True) for row in source_rows] == ["Photo"]


def test_the_chart_is_left_out_when_there_is_nothing_to_draw(client):
    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")

    assert soup.find("canvas", id="correctionsChart") is None
    assert soup.find(id="corrections-by-source") is None
