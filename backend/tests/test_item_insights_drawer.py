"""Tests for Item Insights drawer vs full page rendering and mobile link interception."""

from app.models.category import Category
from app.models.item import Item


def _create_sample_item(db) -> Item:
    cat = Category(name="Produce")
    db.add(cat)
    db.flush()

    item = Item(
        name="Organic Bananas",
        normalized_name="organic bananas",
        category_id=cat.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def test_desktop_request_renders_full_page(db, client):
    """Standard GET without hx-request header renders the full HTML page."""
    item = _create_sample_item(db)
    resp = client.get(f"/items/{item.id}/insights")
    assert resp.status_code == 200
    # Must extend layouts/base.html, containing base doctype / navbar elements
    assert "<!DOCTYPE html>" in resp.text or "<html" in resp.text
    # Should not have the drawer overlay wrapper at the root
    assert "insights-drawer-wrapper" not in resp.text


def test_htmx_request_renders_drawer_wrapper(db, client):
    """GET with hx-request header renders the mobile drawer fragment."""
    item = _create_sample_item(db)
    resp = client.get(
        f"/items/{item.id}/insights",
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    # Must not contain full html page boilerplate
    assert "<!DOCTYPE html>" not in resp.text
    # Must contain the drawer wrapper and touch/accessibility attributes
    assert 'id="insights-drawer-wrapper"' in resp.text
    assert 'x-trap="drawerOpen"' in resp.text
    assert 'role="dialog"' in resp.text
    assert 'aria-modal="true"' in resp.text
    assert "onTouchStart" in resp.text
    assert "closeDrawer" in resp.text


def test_items_page_has_drawer_mount_and_interception(client):
    """The /items page must contain the #insights-drawer-container and mobile interception script."""
    resp = client.get("/items")
    assert resp.status_code == 200
    assert 'id="insights-drawer-container"' in resp.text
    assert '<div id="insights-drawer-wrapper"' not in resp.text  # Drawer not mounted initially
    assert "item-insight-link" in resp.text
    assert "window.innerWidth < 768" in resp.text
