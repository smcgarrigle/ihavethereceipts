"""CM-11: remove, restore, pin and unpin from the corrections page.

Removing is suppression, not deletion, so undo is a second call rather than a
resurrection and the decision survives re-saving the receipt (CM-08). Each
action re-renders the panel, which is why the table lives in a fragment shared
with the full page render.

Editing a lesson is deliberately not here: content_key is derived from the
values, so an edit mints a different lesson and detaches its history. That
needs its own ticket.
"""

from datetime import UTC, datetime, timedelta

import pytest
from bs4 import BeautifulSoup

from app.models import CorrectionOverride, OcrCorrection, Receipt, Store
from app.services.correction_keys import content_key
from app.services.correction_service import (
    get_correction_prompt,
    pinned_keys,
    suppressed_keys,
)

PAGE = "/settings/corrections"

ATTR_BREAKOUT = '"><img src=x onerror=alert(1)>'


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
):
    row = OcrCorrection(
        receipt_id=receipt.id,
        store_id=receipt.store_id,
        field=field,
        input_type=input_type,
        ai_value=ai_value,
        approved_value=approved_value,
        content_key=content_key(receipt.store_id, input_type, field, ai_value, approved_value),
        created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _act(client, key, action, **params):
    return client.post(f"{PAGE}/{key}/{action}", params=params)


def _buttons(markup):
    soup = BeautifulSoup(markup, "html.parser")
    return [b.get_text(strip=True) for b in soup.find_all("button")]


# ---------------------------------------------------------------------------
# The actions do what they say
# ---------------------------------------------------------------------------


def test_remove_suppresses_the_lesson(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    response = _act(client, row.content_key, "remove")

    assert response.status_code == 200
    assert row.content_key in suppressed_keys(db)


def test_remove_keeps_the_lesson_out_of_the_prompt(client, db):
    row = _lesson(db, _receipt(db, _store(db)))
    assert "Whole Milk" in get_correction_prompt(db)

    _act(client, row.content_key, "remove")

    assert get_correction_prompt(db) == ""


def test_restore_reverses_a_removal(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    _act(client, row.content_key, "remove")
    _act(client, row.content_key, "restore")

    assert row.content_key not in suppressed_keys(db)
    assert "Whole Milk" in get_correction_prompt(db)


def test_pin_marks_the_lesson(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    _act(client, row.content_key, "pin")

    assert row.content_key in pinned_keys(db)


def test_pin_reflects_in_the_next_built_block(client, db):
    """The acceptance criterion: a pin takes effect on the next prompt."""
    store = _store(db)
    receipt = _receipt(db, store)
    old = _lesson(db, receipt, "OLD LESSON", "Old Lesson", minutes_ago=500)
    for i in range(12):
        _lesson(db, receipt, f"AI {i}", f"Real {i}", minutes_ago=i)
    assert "Old Lesson" not in get_correction_prompt(db)

    _act(client, old.content_key, "pin")

    block = get_correction_prompt(db)
    assert "Old Lesson" in block
    assert len([line for line in block.splitlines() if line.startswith("- ")]) == 10


def test_unpin_releases_the_lesson(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    _act(client, row.content_key, "pin")
    _act(client, row.content_key, "unpin")

    assert row.content_key not in pinned_keys(db)


def test_one_override_carries_both_decisions(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    _act(client, row.content_key, "pin")
    _act(client, row.content_key, "remove")

    override = db.query(CorrectionOverride).filter_by(content_key=row.content_key).one()
    assert override.pinned is True
    assert override.suppressed is True


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------


def test_an_action_returns_the_panel_fragment(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    body = _act(client, row.content_key, "pin").text

    soup = BeautifulSoup(body, "html.parser")
    assert soup.find(id="corrections-table") is not None
    assert soup.find("html") is None, "an action returned a whole page, not a fragment"


def test_removing_offers_an_undo(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    body = _act(client, row.content_key, "remove").text

    assert "Undo" in _buttons(body)
    assert f"{PAGE}/{row.content_key}/restore" in body


def test_restoring_does_not_offer_an_undo(client, db):
    """Remove and restore must never both claim the bar."""
    row = _lesson(db, _receipt(db, _store(db)))
    _act(client, row.content_key, "remove")

    body = _act(client, row.content_key, "restore").text

    assert "Undo" not in _buttons(body)
    assert "Restored" in body


def test_a_removed_row_offers_restore_not_remove(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    body = _act(client, row.content_key, "remove").text

    buttons = _buttons(body)
    assert "Restore" in buttons
    assert "Remove" not in buttons


def test_a_pinned_row_offers_unpin_not_pin(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    body = _act(client, row.content_key, "pin").text

    buttons = _buttons(body)
    assert "Unpin" in buttons
    assert "Pin" not in buttons


def test_the_page_offers_both_actions_on_a_fresh_lesson(client, db):
    _lesson(db, _receipt(db, _store(db)))

    buttons = _buttons(client.get(PAGE).text)

    assert "Pin" in buttons
    assert "Remove" in buttons


def test_a_row_without_a_key_offers_no_actions(client, db):
    """Rows predating the key column have nothing durable to act on."""
    receipt = _receipt(db, _store(db))
    db.add(
        OcrCorrection(
            receipt_id=receipt.id,
            store_id=receipt.store_id,
            field="name",
            input_type="image",
            ai_value="OLD ROW",
            approved_value="Old Row",
        )
    )
    db.commit()

    body = client.get(PAGE).text

    assert "no key" in body
    assert "Pin" not in _buttons(body)


# ---------------------------------------------------------------------------
# Filters survive an action
# ---------------------------------------------------------------------------


def test_an_action_keeps_the_current_filter(client, db):
    store = _store(db)
    image = _lesson(db, _receipt(db, store), "IMAGE LINE", "Image Line")
    _lesson(db, _receipt(db, store, None), "PASTE LINE", "Paste Line", input_type="paste")

    body = _act(client, image.content_key, "pin", input_type="image").text

    assert "Image Line" in body
    assert "Paste Line" not in body


def test_an_action_without_a_filter_shows_everything(client, db):
    store = _store(db)
    image = _lesson(db, _receipt(db, store), "IMAGE LINE", "Image Line")
    _lesson(db, _receipt(db, store, None), "PASTE LINE", "Paste Line", input_type="paste")

    body = _act(client, image.content_key, "pin").text

    assert "Image Line" in body
    assert "Paste Line" in body


# ---------------------------------------------------------------------------
# Bad input
# ---------------------------------------------------------------------------


def test_an_unknown_action_is_a_404(client, db):
    row = _lesson(db, _receipt(db, _store(db)))

    assert _act(client, row.content_key, "detonate").status_code == 404


def test_an_unknown_key_is_a_404(client, db):
    _lesson(db, _receipt(db, _store(db)))

    assert _act(client, "0" * 40, "remove").status_code == 404


def test_an_unknown_key_changes_nothing(client, db):
    _lesson(db, _receipt(db, _store(db)))

    _act(client, "0" * 40, "remove")

    assert suppressed_keys(db) == set()
    assert db.query(CorrectionOverride).count() == 0


@pytest.mark.parametrize("action", ["remove", "restore", "pin", "unpin"])
def test_every_action_is_a_post(client, db, action):
    """A GET must not change state, however the link is followed."""
    row = _lesson(db, _receipt(db, _store(db)))

    response = client.get(f"{PAGE}/{row.content_key}/{action}")

    assert response.status_code in (404, 405)
    assert db.query(CorrectionOverride).count() == 0


# ---------------------------------------------------------------------------
# The undo bar carries model-derived text
# ---------------------------------------------------------------------------


def test_the_undo_bar_escapes_the_lesson(client, db):
    row = _lesson(db, _receipt(db, _store(db)), f"AI {ATTR_BREAKOUT}", f"OK {ATTR_BREAKOUT}")

    body = _act(client, row.content_key, "remove").text

    assert ATTR_BREAKOUT not in body, (
        "the undo bar emitted a model-derived value verbatim — the summary is "
        "built in Python and must still be escaped by the template"
    )


def test_csrf_travels_with_htmx_requests(client, db):
    """The page relies on the base layout's htmx:configRequest listener.

    CSRF middleware is skipped under TESTING=1, so this asserts the mechanism
    the page depends on is present rather than that a request is rejected.
    """
    _lesson(db, _receipt(db, _store(db)))

    body = client.get(PAGE).text

    assert 'name="csrf-token"' in body
    assert "X-CSRF-Token" in body
