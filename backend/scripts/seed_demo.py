"""
seed_demo.py — Populate the database with realistic demo data.

Run this once on a fresh database to see all dashboard charts, trends, and
analytics pages come alive without uploading any real receipts.

Usage:
    cd backend
    uv run python scripts/seed_demo.py
"""

import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Category, Item, Receipt, ReceiptItem, Store

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
random.seed(42)  # reproducible demo data

STORES = [
    {"name": "Vendor Vic's",     "address": "42 Bargain Blvd"},
    {"name": "WholeGoodness",    "address": "1 Organic Circle"},
    {"name": "AmazingGrocery",   "address": "Online"},
    {"name": "FreshFood Market", "address": "99 Produce Plaza"},
    {"name": "Thrift & Fill",    "address": "500 Bulk Warehouse Dr"},
]

CATEGORIES = [
    "Produce", "Dairy", "Meat & Seafood", "Bakery", "Pantry",
    "Beverages", "Frozen", "Deli", "Snacks", "Health & Beauty",
    "Household", "Other",
]

# item_name: (category, typical_unit_price, unit_type)
ITEM_CATALOG: dict[str, tuple[str, float, str]] = {
    # Produce
    "Spotted Bananas":           ("Produce",          0.27, "lb"),
    "Organicish Fuji Apples":    ("Produce",          1.39, "lb"),
    "Baby Spinach Situation 5oz":("Produce",          3.29, "ea"),
    "Perfectly Ripe Avocados 4pk":("Produce",         5.79, "ea"),
    "Suspiciously Round Tomatoes":("Produce",         4.19, "ea"),
    "Broccoli Chunks":           ("Produce",          1.69, "lb"),
    "Bag of Limes (Many)":       ("Produce",          3.49, "ea"),
    "Gourmet Carrots":           ("Produce",          1.99, "ea"),

    # Dairy
    "Whole Milk (The Good Kind)":("Dairy",            4.39, "ea"),
    "Greek Yogurt Situation 32oz":("Dairy",           5.79, "ea"),
    "Cage-Ish Free Eggs 12ct":   ("Dairy",            4.89, "ea"),
    "Fancy Sharp Cheddar 2lb":   ("Dairy",            8.29, "ea"),
    "Unsalted Fancy Butter 1lb": ("Dairy",            5.19, "ea"),
    "Oat Drink (Not Milk) 64oz": ("Dairy",            5.99, "ea"),

    # Meat & Seafood
    "Free-Range Chicken Breast": ("Meat & Seafood",   6.89, "lb"),
    "Beef That's Mostly Lean":   ("Meat & Seafood",   5.69, "lb"),
    "Salmon From The Ocean":     ("Meat & Seafood",   9.89, "lb"),
    "Big Shrimp (Frozen Bag)":   ("Meat & Seafood",  12.99, "ea"),

    # Bakery
    "Sourdough Vibes Loaf":      ("Bakery",           4.89, "ea"),
    "Multigrain Everything Bagels 6ct":("Bakery",     3.39, "ea"),
    "Pretzel Buns (Fancy)":      ("Bakery",           3.99, "ea"),

    # Pantry
    "Old-Fashioned Oats 42oz":   ("Pantry",           4.19, "ea"),
    "Brown Rice (The Good One) 5lb":("Pantry",        6.39, "ea"),
    "Extra Virginal Olive Oil":  ("Pantry",          10.79, "ea"),
    "Beans (Black, Canned)":     ("Pantry",           1.19, "ea"),
    "Penne Pasta 1lb":           ("Pantry",           1.69, "ea"),
    "Tomato Sauce Classic 24oz": ("Pantry",           3.89, "ea"),
    "Suspiciously Delicious Almond Butter 16oz":("Pantry", 9.29, "ea"),
    "Coconut Aminos (Fancy Soy Sauce)":("Pantry",    5.99, "ea"),

    # Beverages
    "Bubbly Water 12pk":         ("Beverages",        5.89, "ea"),
    "OJ (With Pulp) 52oz":       ("Beverages",        4.89, "ea"),
    "Cold Brew Concentrate 32oz":("Beverages",        7.39, "ea"),
    "Funky Fermented Tea 16oz":  ("Beverages",        3.69, "ea"),
    "Electrolyte Drink (Melon)": ("Beverages",        2.49, "ea"),

    # Frozen
    "Margherita Pizza (Fancy)":  ("Frozen",           7.89, "ea"),
    "Edamame Beans 2lb":         ("Frozen",           5.39, "ea"),
    "Mixed Berries Big Bag 3lb": ("Frozen",           8.89, "ea"),
    "Cauliflower Crust Pizza":   ("Frozen",           8.49, "ea"),

    # Deli
    "Fancy Ham Slices 6oz":      ("Deli",             5.89, "ea"),
    "Hummus Original 17oz":      ("Deli",             4.39, "ea"),
    "Pesto Situation 7oz":       ("Deli",             5.49, "ea"),

    # Snacks
    "Artisanal Trail Mix 1lb":   ("Snacks",           7.39, "ea"),
    "Very Dark Chocolate 3.5oz": ("Snacks",           2.89, "ea"),
    "Sea Salt Kettle Chips":     ("Snacks",           4.19, "ea"),
    "Rice Cakes (Plain Sadness)":("Snacks",           3.29, "ea"),

    # Household
    "Dish Soap (Lemon-ish) 32oz":("Household",        4.89, "ea"),
    "Paper Towels (Strong) 6-Roll":("Household",      9.89, "ea"),
    "Laundry Detergent 96oz":    ("Household",       14.79, "ea"),
    "Sponges (Fancy) 6pk":       ("Household",        4.49, "ea"),

    # Health & Beauty
    "Vitamin D (Sunshine in a Pill)":("Health & Beauty", 12.79, "ea"),
    "Floss Picks 150ct":         ("Health & Beauty",  4.89, "ea"),
    "Melatonin 5mg 60ct":        ("Health & Beauty",  8.99, "ea"),
}

# Which stores stock which items (realistic distribution)
STORE_CATALOG: dict[str, list[str]] = {
    "Vendor Vic's": [
        "Spotted Bananas", "Organicish Fuji Apples", "Broccoli Chunks",
        "Whole Milk (The Good Kind)", "Cage-Ish Free Eggs 12ct", "Unsalted Fancy Butter 1lb",
        "Beef That's Mostly Lean", "Sourdough Vibes Loaf", "Old-Fashioned Oats 42oz",
        "Beans (Black, Canned)", "Penne Pasta 1lb", "Tomato Sauce Classic 24oz",
        "OJ (With Pulp) 52oz", "Bubbly Water 12pk", "Margherita Pizza (Fancy)",
        "Sea Salt Kettle Chips", "Dish Soap (Lemon-ish) 32oz", "Paper Towels (Strong) 6-Roll",
        "Laundry Detergent 96oz",
    ],
    "WholeGoodness": [
        "Organicish Fuji Apples", "Baby Spinach Situation 5oz", "Perfectly Ripe Avocados 4pk",
        "Gourmet Carrots", "Whole Milk (The Good Kind)", "Greek Yogurt Situation 32oz",
        "Oat Drink (Not Milk) 64oz", "Unsalted Fancy Butter 1lb",
        "Free-Range Chicken Breast", "Salmon From The Ocean",
        "Sourdough Vibes Loaf", "Extra Virginal Olive Oil",
        "Suspiciously Delicious Almond Butter 16oz", "Coconut Aminos (Fancy Soy Sauce)",
        "Cold Brew Concentrate 32oz", "Funky Fermented Tea 16oz",
        "Mixed Berries Big Bag 3lb", "Pesto Situation 7oz",
        "Very Dark Chocolate 3.5oz", "Vitamin D (Sunshine in a Pill)", "Floss Picks 150ct",
    ],
    "AmazingGrocery": [
        "Spotted Bananas", "Baby Spinach Situation 5oz", "Perfectly Ripe Avocados 4pk",
        "Cage-Ish Free Eggs 12ct", "Whole Milk (The Good Kind)", "Greek Yogurt Situation 32oz",
        "Free-Range Chicken Breast", "Beef That's Mostly Lean", "Big Shrimp (Frozen Bag)",
        "Sourdough Vibes Loaf", "Penne Pasta 1lb", "Tomato Sauce Classic 24oz",
        "Cold Brew Concentrate 32oz", "Electrolyte Drink (Melon)",
        "Margherita Pizza (Fancy)", "Hummus Original 17oz",
        "Dish Soap (Lemon-ish) 32oz", "Paper Towels (Strong) 6-Roll",
        "Vitamin D (Sunshine in a Pill)", "Melatonin 5mg 60ct",
    ],
    "FreshFood Market": [
        "Spotted Bananas", "Organicish Fuji Apples", "Baby Spinach Situation 5oz",
        "Suspiciously Round Tomatoes", "Bag of Limes (Many)", "Gourmet Carrots",
        "Whole Milk (The Good Kind)", "Fancy Sharp Cheddar 2lb", "Cage-Ish Free Eggs 12ct",
        "Salmon From The Ocean", "Fancy Ham Slices 6oz", "Pesto Situation 7oz",
        "Hummus Original 17oz", "Funky Fermented Tea 16oz", "Bubbly Water 12pk",
        "Edamame Beans 2lb", "Mixed Berries Big Bag 3lb",
        "Artisanal Trail Mix 1lb", "Rice Cakes (Plain Sadness)",
    ],
    "Thrift & Fill": [
        "Organicish Fuji Apples", "Suspiciously Round Tomatoes", "Broccoli Chunks",
        "Cage-Ish Free Eggs 12ct", "Fancy Sharp Cheddar 2lb", "Unsalted Fancy Butter 1lb",
        "Beef That's Mostly Lean", "Salmon From The Ocean", "Big Shrimp (Frozen Bag)",
        "Old-Fashioned Oats 42oz", "Brown Rice (The Good One) 5lb",
        "Extra Virginal Olive Oil", "Beans (Black, Canned)",
        "Suspiciously Delicious Almond Butter 16oz",
        "Bubbly Water 12pk", "OJ (With Pulp) 52oz",
        "Mixed Berries Big Bag 3lb", "Cauliflower Crust Pizza",
        "Artisanal Trail Mix 1lb", "Paper Towels (Strong) 6-Roll",
        "Laundry Detergent 96oz", "Sponges (Fancy) 6pk", "Floss Picks 150ct",
    ],
}


def vary(price: float, pct: float = 0.09) -> float:
    """Apply small random price variation to simulate real-world price changes."""
    return round(price * random.uniform(1 - pct, 1 + pct), 2)


def build_schedule() -> list[tuple[str, date, list[str]]]:
    """Return list of (store_name, purchase_date, [item_names])."""
    today = date.today()
    schedule = []

    # Bi-weekly Vendor Vic's runs (the main budget store)
    for weeks_ago in range(16, 0, -1):
        if weeks_ago % 2 == 0:
            d = today - timedelta(weeks=weeks_ago, days=random.randint(0, 2))
            items = random.sample(STORE_CATALOG["Vendor Vic's"], k=random.randint(6, 12))
            schedule.append(("Vendor Vic's", d, items))

    # Monthly Thrift & Fill runs (bulk warehouse)
    for months_ago in [3, 2, 1]:
        d = today - timedelta(days=months_ago * 30 + random.randint(-3, 3))
        items = random.sample(STORE_CATALOG["Thrift & Fill"], k=random.randint(8, 14))
        schedule.append(("Thrift & Fill", d, items))

    # Occasional AmazingGrocery orders (online)
    for weeks_ago in [12, 7, 3, 1]:
        d = today - timedelta(weeks=weeks_ago, days=random.randint(0, 1))
        items = random.sample(STORE_CATALOG["AmazingGrocery"], k=random.randint(4, 8))
        schedule.append(("AmazingGrocery", d, items))

    # A few WholeGoodness trips (premium store)
    for weeks_ago in [14, 9, 5]:
        d = today - timedelta(weeks=weeks_ago, days=random.randint(0, 2))
        items = random.sample(STORE_CATALOG["WholeGoodness"], k=random.randint(4, 8))
        schedule.append(("WholeGoodness", d, items))

    # A few FreshFood Market trips
    for weeks_ago in [11, 6, 2]:
        d = today - timedelta(weeks=weeks_ago, days=random.randint(0, 1))
        items = random.sample(STORE_CATALOG["FreshFood Market"], k=random.randint(5, 9))
        schedule.append(("FreshFood Market", d, items))

    return sorted(schedule, key=lambda x: x[1])


def seed() -> None:
    db = SessionLocal()
    try:
        print("🌱 Seeding demo data for Grocery Tracker...\n")

        # ---- Stores ----
        store_map: dict[str, Store] = {}
        for s in STORES:
            existing = db.query(Store).filter(Store.name == s["name"]).first()
            if existing:
                store_map[s["name"]] = existing
                print(f"  · Store exists: {s['name']}")
            else:
                store = Store(name=s["name"], address=s["address"])
                db.add(store)
                db.flush()
                store_map[s["name"]] = store
                print(f"  + Added store: {s['name']}")

        # ---- Categories ----
        cat_map: dict[str, Category] = {}
        for c in CATEGORIES:
            existing = db.query(Category).filter(Category.name == c).first()
            if existing:
                cat_map[c] = existing
            else:
                cat = Category(name=c)
                db.add(cat)
                db.flush()
                cat_map[c] = cat
        print(f"\n  ✓ {len(CATEGORIES)} categories ready")

        # ---- Master Items (Item table — deduplicated product catalog) ----
        item_obj_map: dict[str, Item] = {}
        for item_name, (cat_name, _, _) in ITEM_CATALOG.items():
            existing = db.query(Item).filter(Item.name == item_name).first()
            if existing:
                item_obj_map[item_name] = existing
            else:
                item_obj = Item(
                    name=item_name,
                    normalized_name=item_name.lower(),
                    category_id=cat_map[cat_name].id,
                )
                db.add(item_obj)
                db.flush()
                item_obj_map[item_name] = item_obj
        print(f"  ✓ {len(ITEM_CATALOG)} items in catalog")

        # ---- Receipts & ReceiptItems ----
        schedule = build_schedule()
        receipt_count = 0
        receipt_item_count = 0

        for store_name, receipt_date, item_names in schedule:
            store = store_map[store_name]

            line_items_data = []
            total_amount = 0.0

            for item_name in item_names:
                cat_name, base_price, unit_type = ITEM_CATALOG[item_name]
                unit_price = vary(base_price)
                qty: float

                if unit_type == "lb":
                    qty = round(random.uniform(0.8, 2.5), 2)
                else:
                    qty = float(random.choice([1, 1, 1, 2]))

                line_total = round(unit_price * qty, 2)
                total_amount += line_total
                line_items_data.append({
                    "name": item_name,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "total": line_total,
                    "unit_type": unit_type,
                    "category": cat_name,
                })

            total_amount = round(total_amount, 2)

            receipt = Receipt(
                store_id=store.id,
                purchase_date=datetime.combine(receipt_date, datetime.min.time()),
                total_amount=total_amount,
                status="completed",
                ocr_data=json.dumps({
                    "store": store_name,
                    "items": line_items_data,
                    "total": total_amount,
                }),
            )
            db.add(receipt)
            db.flush()
            receipt_count += 1

            for li in line_items_data:
                item_obj = item_obj_map.get(li["name"])
                ri = ReceiptItem(
                    receipt_id=receipt.id,
                    item_id=item_obj.id if item_obj else None,
                    quantity=li["quantity"],
                    price=li["total"],
                    unit_price=li["unit_price"],
                    unit_type=li["unit_type"],
                )
                db.add(ri)
                receipt_item_count += 1

        db.commit()
        print(f"\n  ✅ Created {receipt_count} receipts with {receipt_item_count} line items")
        if schedule:
            print(f"  📅 Date range: {schedule[0][1]} → {schedule[-1][1]}")
        print(f"  🏪 Stores: {', '.join(s['name'] for s in STORES)}")
        print(f"  🛒 {len(ITEM_CATALOG)} unique products across {len(CATEGORIES)} categories")
        print("\n🚀 Demo data ready! Start the server and open http://127.0.0.1:8000\n")

    except Exception as e:
        db.rollback()
        print(f"\n❌ Seeding failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
