"""Stray `</div>`s: the price panel rendered outside the card it belongs to.

The item insights page closed its Purchase History card immediately after the
purchase timeline, so the lowest/average/highest strip and the sparkline fell
outside the card and floated on the page background. Two more templates carried
an extra `</div>` before `{% endblock %}`, and the layout never closed
`#mobile-menu` at all — every page was one div short, which is what made the
insights page look balanced while it was nested wrong.

Browsers recover from all of that silently: an unmatched end tag is ignored and
an unclosed div is closed at the parent. So the rendered DOM never complained,
and only the one real nesting error was visible. Hence a test on the markup
itself, not on the DOM it happens to produce.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.models import Category, Item, Receipt, ReceiptItem, Store

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _balance(markup: str) -> tuple[int, int]:
    """(net depth, lowest depth reached) counting only div tags."""
    depth, low = 0, 0
    for tag in re.finditer(r"<(/?)div\b", markup):
        depth += -1 if tag.group(1) else 1
        low = min(low, depth)
    return depth, low


@pytest.mark.parametrize(
    "template", sorted(TEMPLATES.rglob("*.html")), ids=lambda p: str(p.relative_to(TEMPLATES))
)
def test_every_template_balances_its_divs(template):
    net, low = _balance(template.read_text())
    assert low == 0, f"{template.name} closes a div it never opened"
    assert net == 0, (
        f"{template.name} leaves {net} div(s) open"
        if net > 0
        else f"{template.name} has {-net} stray closing div(s)"
    )


class TestThePricePanelIsInsideItsCard:
    @pytest.fixture
    def flour(self, db):
        store = Store(name="Rainbow Grocery")
        category = Category(name="Pantry")
        db.add_all([store, category])
        db.commit()
        item = Item(
            name="00 PIZZA FLOUR", normalized_name="00 pizza flour", category_id=category.id
        )
        db.add(item)
        db.commit()
        for day, (qty, price, weight) in enumerate(
            [(1.0, 3.06, 1.75), (1.42, 1.7535211, 1.42), (1.42, 1.4788732, 1.42)], start=1
        ):
            receipt = Receipt(
                store_id=store.id,
                status="completed",
                purchase_date=datetime.datetime(2026, 1, day),
                total_amount=price * qty,
            )
            db.add(receipt)
            db.commit()
            db.add(
                ReceiptItem(
                    receipt_id=receipt.id,
                    item_id=item.id,
                    quantity=qty,
                    price=price,
                    weight=weight,
                    unit_type="lb",
                )
            )
            db.commit()
        return item

    def test_the_sparkline_shares_the_card_with_the_timeline(self, client, flour):
        soup = BeautifulSoup(client.get(f"/items/{flour.id}/insights").text, "html.parser")

        chart = soup.find(id="priceTrendChart")
        assert chart is not None, "no sparkline on the page"

        card = chart.find_parent("div", class_="bg-bgCard")
        assert card is not None, "the sparkline is not inside any card"

        timeline = card.find("div", class_="flex-nowrap")
        assert timeline is not None, (
            "the sparkline's card does not hold the purchase timeline — "
            "the card is being closed before the price panel"
        )

    def test_the_summary_strip_shares_it_too(self, client, flour):
        soup = BeautifulSoup(client.get(f"/items/{flour.id}/insights").text, "html.parser")

        card = soup.find(id="priceTrendChart").find_parent("div", class_="bg-bgCard")
        assert "Price per lb" in card.get_text()
        assert "Lowest" in card.get_text()
