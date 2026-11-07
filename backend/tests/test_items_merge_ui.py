"""Regression tests for item search merge UI and canonical duplicate detection."""

from bs4 import BeautifulSoup

from app.models.category import Category
from app.models.item import Item
from app.services.ext_matcher import clean_retail_title


def test_search_items_merge_ui_allows_one_keep_and_one_merge(client, db):
    """Selecting 1 Keep (radio) + 1 Merge (checkbox) must not fail with 'selectedItems.length < 2'."""
    cat = Category(name="Produce")
    db.add(cat)
    db.flush()

    item1 = Item(
        name="Russet Potatoes, 5 Lb",
        normalized_name="russet potatoes, 5 lb",
        category_id=cat.id,
    )
    item2 = Item(
        name="Amazon Grocery, Russet Potatoes,",
        normalized_name="amazon grocery, russet potatoes,",
        category_id=cat.id,
    )
    db.add_all([item1, item2])
    db.commit()

    resp = client.get("/api/items/search?q=russet")
    assert resp.status_code == 200
    html = resp.text

    # Bug 1: selectedItems only tracks checkboxes, so selectedItems.length < 2
    # blocked merging when the user checked 1 radio (Keep) + 1 checkbox (Merge).
    assert "selectedItems.length < 2" not in html

    # Bug 2: Alpine inline attributes must not use 'const ' or 'let '
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.find_all(attrs={"@click": True}):
        click_code = el.get("@click") or ""
        assert "const " not in click_code
        assert "let " not in click_code

    # Bug 3: A single <label> must not wrap both the radio and checkbox inputs
    for label in soup.find_all("label"):
        inputs = label.find_all("input")
        assert len(inputs) <= 1, "A <label> must not wrap multiple <input> elements"


def test_clean_retail_title_strips_amazon_grocery_and_size():
    """clean_retail_title should normalize all three Russet Potato variants to 'russet potatoes'."""
    assert clean_retail_title("Russet Potatoes, 5 Lb") == "russet potatoes"
    assert clean_retail_title("Amazon Grocery, Russet Potatoes,") == "russet potatoes"
    assert clean_retail_title("Russet Potatoes") == "russet potatoes"


def test_list_duplicates_groups_canonical_retail_variants_with_merge_action(client, db):
    """/api/items/duplicates should group brand/size variants and render a direct Merge action."""
    cat = Category(name="Produce")
    db.add(cat)
    db.flush()

    item1 = Item(
        name="Russet Potatoes, 5 Lb",
        normalized_name="russet potatoes, 5 lb",
        category_id=cat.id,
    )
    item2 = Item(
        name="Amazon Grocery, Russet Potatoes,",
        normalized_name="amazon grocery, russet potatoes,",
        category_id=cat.id,
    )
    item3 = Item(
        name="Russet Potatoes",
        normalized_name="russet potatoes",
        category_id=cat.id,
    )
    db.add_all([item1, item2, item3])
    db.commit()

    resp = client.get("/api/items/duplicates")
    assert resp.status_code == 200
    html = resp.text

    assert "Russet Potatoes, 5 Lb" in html
    assert "Amazon Grocery, Russet Potatoes," in html
    assert "/api/items/merge" in html
