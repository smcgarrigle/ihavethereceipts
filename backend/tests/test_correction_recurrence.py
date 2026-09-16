"""CM-12: flag lessons that keep recurring.

Usage measures exposure, not value. A lesson the model was already given and
still got wrong is one worth removing, so a correction recorded *after* its
first use counts as a recurrence.

It reads zero until the usage log has history: on the live database every
lesson shows nothing, because usage logging shipped with CM-07 and no receipt
has been through OCR since.
"""

from datetime import UTC, datetime, timedelta

import pytest
from bs4 import BeautifulSoup

from app.api.settings_router import CORRECTION_SORTS, _corrections_context
from app.models import CorrectionUsage, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import _recurrences_after, list_corrections

PAGE = "/settings/corrections"


def _naive(moment: datetime) -> datetime:
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


def _lesson(db, receipt, ai_value="MLK WHL GAL", approved_value="Whole Milk", days_ago=0):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field="name",
        input_type="image",
        ai_value=ai_value,
        approved_value=approved_value,
        content_key=content_key(receipt.store_id, "image", "name", ai_value, approved_value),
        created_at=datetime.now(UTC) - timedelta(days=days_ago),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _used(db, key, receipt, days_ago=0):
    db.add(
        CorrectionUsage(
            content_key=key,
            receipt_id=receipt.id,
            used_at=_naive(datetime.now(UTC) - timedelta(days=days_ago)),
        )
    )
    db.commit()


def _row_for(db, ai_value="MLK WHL GAL"):
    return next(r for r in list_corrections(db) if r["ai_value"] == ai_value)


# ---------------------------------------------------------------------------
# The count itself
# ---------------------------------------------------------------------------


def test_a_never_used_lesson_has_not_recurred(db):
    """A correction cannot have recurred against advice never given."""
    store = _store(db)
    _lesson(db, _receipt(db, store), days_ago=5)
    _lesson(db, _receipt(db, store, "/data/uploads/b.jpg"), days_ago=1)

    row = _row_for(db)

    assert row["seen"] == 2
    assert row["recurred"] == 0


def test_a_correction_after_first_use_counts(db):
    store = _store(db)
    first = _lesson(db, _receipt(db, store), days_ago=10)
    target = _receipt(db, store, "/data/uploads/t.jpg")
    _used(db, first.content_key, target, days_ago=5)
    _lesson(db, _receipt(db, store, "/data/uploads/b.jpg"), days_ago=1)

    row = _row_for(db)

    assert row["seen"] == 2
    assert row["recurred"] == 1


def test_a_correction_before_first_use_does_not_count(db):
    store = _store(db)
    first = _lesson(db, _receipt(db, store), days_ago=10)
    _lesson(db, _receipt(db, store, "/data/uploads/b.jpg"), days_ago=8)
    target = _receipt(db, store, "/data/uploads/t.jpg")
    _used(db, first.content_key, target, days_ago=1)

    assert _row_for(db)["recurred"] == 0


def test_a_correction_recorded_at_the_moment_of_use_is_not_a_recurrence():
    """It already existed when it was sent, so it is not a repeat of it.

    This pins the comparison as strictly after: counting the cutoff itself
    would treat the very correction that was sent as having recurred.
    """
    now = datetime.now(UTC)

    assert _recurrences_after([now], now) == 0
    assert _recurrences_after([now + timedelta(seconds=1)], now) == 1


def test_the_earliest_use_is_the_cutoff(db):
    """Later uses must not shrink the count."""
    store = _store(db)
    first = _lesson(db, _receipt(db, store), days_ago=30)
    target = _receipt(db, store, "/data/uploads/t.jpg")
    _used(db, first.content_key, target, days_ago=20)
    _used(db, first.content_key, target, days_ago=1)
    for day in (15, 10, 5):
        _lesson(db, _receipt(db, store, f"/data/uploads/{day}.jpg"), days_ago=day)

    assert _row_for(db)["recurred"] == 3


def test_recurrence_is_per_lesson(db):
    store = _store(db)
    milk = _lesson(db, _receipt(db, store), days_ago=10)
    spinach = _lesson(db, _receipt(db, store, "/data/uploads/s.jpg"), "ORG SPNCH", "Spinach", 10)
    target = _receipt(db, store, "/data/uploads/t.jpg")
    _used(db, milk.content_key, target, days_ago=5)
    _used(db, spinach.content_key, target, days_ago=5)
    _lesson(db, _receipt(db, store, "/data/uploads/b.jpg"), days_ago=1)

    assert _row_for(db)["recurred"] == 1
    assert _row_for(db, "ORG SPNCH")["recurred"] == 0


@pytest.mark.parametrize(
    ("recorded_offsets", "used_offset", "expected"),
    [
        ([], 5, 0),
        ([1], 5, 1),
        ([10], 5, 0),
        ([1, 2, 3], 5, 3),
        ([1, 10], 5, 1),
    ],
)
def test_the_helper_counts_what_came_after(recorded_offsets, used_offset, expected):
    now = datetime.now(UTC)
    recorded = [now - timedelta(days=d) for d in recorded_offsets]
    assert _recurrences_after(recorded, now - timedelta(days=used_offset)) == expected


def test_the_helper_handles_naive_and_aware_together():
    """created_at is written aware but stored naive; used_at is a naive column."""
    now = datetime.now(UTC)
    aware = [now - timedelta(days=1)]
    naive = [(now - timedelta(days=1)).replace(tzinfo=None)]
    cutoff_naive = (now - timedelta(days=5)).replace(tzinfo=None)
    cutoff_aware = now - timedelta(days=5)

    assert _recurrences_after(aware, cutoff_naive) == 1
    assert _recurrences_after(naive, cutoff_aware) == 1
    assert _recurrences_after(aware, None) == 0


# ---------------------------------------------------------------------------
# What the page shows
# ---------------------------------------------------------------------------


def _cells(body):
    soup = BeautifulSoup(body, "html.parser")
    return soup.find(id="corrections-table").find("tbody").find_all("tr")[0].find_all("td")


def test_the_table_has_a_recurred_column(client, db):
    _lesson(db, _receipt(db, _store(db)))

    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")
    headers = [th.get_text(strip=True) for th in soup.find(id="corrections-table").find_all("th")]

    assert "Recurred" in headers
    assert len(headers) == 8


def test_no_recurrence_shows_a_dash(client, db):
    _lesson(db, _receipt(db, _store(db)))

    assert _cells(client.get(PAGE).text)[6].get_text(strip=True) == "—"


def test_one_recurrence_shows_a_bare_count(client, db):
    """The label is for a pattern, not a single repeat."""
    store = _store(db)
    first = _lesson(db, _receipt(db, store), days_ago=10)
    _used(db, first.content_key, _receipt(db, store, "/data/uploads/t.jpg"), days_ago=5)
    _lesson(db, _receipt(db, store, "/data/uploads/b.jpg"), days_ago=1)

    body = client.get(PAGE).text

    assert _cells(body)[6].get_text(strip=True) == "1"
    assert "times after use" not in body


def test_two_recurrences_are_flagged(client, db):
    store = _store(db)
    first = _lesson(db, _receipt(db, store), days_ago=30)
    _used(db, first.content_key, _receipt(db, store, "/data/uploads/t.jpg"), days_ago=20)
    for day in (10, 5):
        _lesson(db, _receipt(db, store, f"/data/uploads/{day}.jpg"), days_ago=day)

    body = client.get(PAGE).text

    assert "recurred 2 times after use" in body


def test_the_tally_counts_recurring_lessons(client, db):
    store = _store(db)
    first = _lesson(db, _receipt(db, store), days_ago=30)
    _used(db, first.content_key, _receipt(db, store, "/data/uploads/t.jpg"), days_ago=20)
    for day in (10, 5):
        _lesson(db, _receipt(db, store, f"/data/uploads/{day}.jpg"), days_ago=day)

    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")

    assert "1 recurring" in soup.find(id="corrections-tally").get_text()


def test_the_tally_omits_recurring_when_there_are_none(client, db):
    _lesson(db, _receipt(db, _store(db)))

    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")

    assert "recurring" not in soup.find(id="corrections-tally").get_text()


# ---------------------------------------------------------------------------
# Sorting by it
# ---------------------------------------------------------------------------


def test_the_page_offers_the_sort(client, db):
    _lesson(db, _receipt(db, _store(db)))

    soup = BeautifulSoup(client.get(PAGE).text, "html.parser")
    options = [o.get("value") for o in soup.find(id="filter-sort").find_all("option")]

    assert options == list(CORRECTION_SORTS)


def test_sorting_by_recurrence_puts_the_worst_first(db):
    """The two sorts must disagree, or this proves nothing.

    QUIET leads on recent use; NOISY leads on recurrences. Each sort has to
    pick its own winner.
    """
    store = _store(db)
    quiet = _lesson(db, _receipt(db, store), "QUIET", "Quiet Lesson", days_ago=30)
    noisy = _lesson(db, _receipt(db, store, "/data/uploads/n.jpg"), "NOISY", "Noisy Lesson", 30)
    target = _receipt(db, store, "/data/uploads/t.jpg")
    _used(db, quiet.content_key, target, days_ago=1)
    _used(db, noisy.content_key, target, days_ago=20)
    for day in (10, 5, 2):
        _lesson(db, _receipt(db, store, f"/data/uploads/n{day}.jpg"), "NOISY", "Noisy Lesson", day)

    by_recurrence = _corrections_context(db, "", "", "recurred")["rows"]
    by_use = _corrections_context(db, "", "", "used")["rows"]

    assert by_recurrence[0]["ai_value"] == "NOISY"
    assert by_recurrence[0]["recurred"] == 3
    assert by_recurrence[1]["ai_value"] == "QUIET"
    assert by_recurrence[1]["recurred"] == 0

    # The default sort reaches the opposite answer, so the recurrence sort is
    # doing the ordering rather than riding on a coincidence.
    assert by_use[0]["ai_value"] == "QUIET"
    assert by_use[0]["used_this_week"] == 1


def test_an_unknown_sort_falls_back(client, db):
    _lesson(db, _receipt(db, _store(db)))

    response = client.get(PAGE, params={"sort": "sideways"})

    assert response.status_code == 200
    soup = BeautifulSoup(response.text, "html.parser")
    selected = soup.find(id="filter-sort").find("option", selected=True)
    assert selected.get("value") == "used"


def test_the_sort_survives_an_action(client, db):
    store = _store(db)
    row = _lesson(db, _receipt(db, store))

    body = client.post(f"{PAGE}/{row.content_key}/pin", params={"sort": "recurred"}).text

    assert BeautifulSoup(body, "html.parser").find(id="corrections-table") is not None


def test_the_sort_is_carried_in_the_form(client, db):
    _lesson(db, _receipt(db, _store(db)))

    soup = BeautifulSoup(client.get(PAGE, params={"sort": "recurred"}).text, "html.parser")
    selected = soup.find(id="filter-sort").find("option", selected=True)

    assert selected.get("value") == "recurred"
