"""
seed_demo.py — Populate the database with realistic demo data.

Run this once on a fresh database to see all dashboard charts, trends, and
analytics pages come alive without uploading any real receipts.

Twelve fictional stores with distinct personalities (a bulk warehouse, a
salsa boutique, a gas station, a protein-powder exchange, two bakeries…)
generate ~15 weeks of purchase history. Roughly two-thirds of the food
catalog carries per-100g nutrient data so the nutrition analytics, coverage
badges, and X-Ray queue all demo realistically — including what *missing*
data looks like.

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
    {"name": "VendorVics",                "address": "42 Bargain Blvd"},
    {"name": "SpaceWay",                  "address": "1 Orbital Parkway"},
    {"name": "WhollyFUD",                 "address": "108 Enlightenment Way"},
    {"name": "MeatBagFuels",              "address": "7 Carnivore Court"},
    {"name": "Salsa Emporium",            "address": "5 Scoville Square"},
    {"name": "The FeedLoft",              "address": "500 Bulk Warehouse Dr"},
    {"name": "B2BSaasoons",               "address": "Suite 200, Enterprise Park"},
    {"name": "LuridLurie's Gas",          "address": "Exit 13, Interstate 5"},
    {"name": "Tartanula's",               "address": "8 Legs Lane"},
    {"name": "L'UnOeufPun Bakery",        "address": "12 Rue du Croissant"},
    {"name": "Peptide Inferance Exchange", "address": "Online"},
    {"name": "BundtCake & More",          "address": "360 Ring Road"},
]

CATEGORIES = [
    "Produce", "Dairy", "Meat & Seafood", "Bakery", "Pantry",
    "Beverages", "Frozen", "Deli", "Snacks", "Health & Beauty",
    "Household", "Other",
]

# Per-100g nutrient profiles (approximate real-world values).
# Keys follow the OpenFoodFacts convention used by nutrition_utils.
# (kcal, carbs_g, sugars_g, protein_g, fat_g, satfat_g, sodium_g)
_P = {
    "banana":        (89, 23, 12, 1.1, 0.3, 0.1, 0.001),
    "apple":         (52, 14, 10, 0.3, 0.2, 0.0, 0.001),
    "spinach":       (23, 3.6, 0.4, 2.9, 0.4, 0.1, 0.079),
    "avocado":       (160, 8.5, 0.7, 2.0, 14.7, 2.1, 0.007),
    "tomato":        (18, 3.9, 2.6, 0.9, 0.2, 0.0, 0.005),
    "broccoli":      (34, 6.6, 1.7, 2.8, 0.4, 0.0, 0.033),
    "carrot":        (41, 9.6, 4.7, 0.9, 0.2, 0.0, 0.069),
    "pepper":        (31, 6.0, 4.2, 1.0, 0.3, 0.0, 0.004),
    "milk":          (61, 4.8, 5.0, 3.2, 3.3, 1.9, 0.043),
    "greek_yogurt":  (59, 3.6, 3.2, 10.0, 0.4, 0.1, 0.036),
    "eggs":          (143, 0.7, 0.4, 12.6, 9.5, 3.1, 0.142),
    "cheddar":       (403, 1.3, 0.5, 24.9, 33.0, 21.0, 0.62),
    "butter":        (717, 0.1, 0.1, 0.9, 81.0, 51.0, 0.011),
    "oat_milk":      (47, 7.7, 4.2, 1.0, 1.5, 0.2, 0.04),
    "chicken":       (165, 0, 0, 31.0, 3.6, 1.0, 0.074),
    "beef":          (250, 0, 0, 26.0, 15.0, 6.0, 0.072),
    "lamb":          (294, 0, 0, 25.0, 21.0, 9.0, 0.072),
    "salmon":        (208, 0, 0, 20.0, 13.0, 3.0, 0.059),
    "shrimp":        (99, 0.2, 0, 24.0, 0.3, 0.1, 0.111),
    "bacon":         (541, 1.4, 1.0, 37.0, 42.0, 14.0, 1.717),
    "bread":         (289, 56.0, 2.0, 9.2, 1.8, 0.4, 0.6),
    "bagel":         (250, 49.0, 5.0, 10.0, 1.5, 0.3, 0.43),
    "croissant":     (406, 45.0, 11.0, 8.0, 21.0, 11.0, 0.47),
    "quiche":        (230, 18.0, 2.0, 8.0, 14.0, 7.0, 0.4),
    "bundt":         (400, 52.0, 35.0, 4.0, 19.0, 5.0, 0.3),
    "tart":          (300, 40.0, 22.0, 3.5, 14.0, 7.0, 0.2),
    "shortbread":    (502, 64.0, 17.0, 5.0, 26.0, 16.0, 0.4),
    "jam":           (250, 65.0, 49.0, 0.3, 0.1, 0.0, 0.03),
    "oats":          (389, 66.0, 1.0, 17.0, 7.0, 1.2, 0.002),
    "rice":          (370, 77.0, 0.7, 7.5, 2.7, 0.5, 0.007),
    "quinoa":        (368, 64.0, 6.0, 14.0, 6.0, 0.7, 0.005),
    "flour":         (364, 76.0, 0.3, 10.0, 1.0, 0.2, 0.002),
    "olive_oil":     (884, 0, 0, 0, 100.0, 14.0, 0.002),
    "black_beans":   (341, 62.0, 2.0, 21.0, 1.4, 0.4, 0.005),
    "pasta":         (371, 75.0, 2.7, 13.0, 1.5, 0.3, 0.006),
    "tomato_sauce":  (29, 5.0, 3.5, 1.5, 0.2, 0.0, 0.4),
    "almond_butter": (614, 19.0, 4.4, 21.0, 56.0, 4.2, 0.002),
    "salsa":         (36, 7.0, 4.0, 1.5, 0.2, 0.0, 0.7),
    "hot_sauce":     (12, 2.0, 1.0, 0.5, 0.4, 0.0, 2.6),
    "queso":         (313, 9.0, 3.0, 7.0, 27.0, 15.0, 1.1),
    "tortilla_chips": (503, 63.0, 1.0, 7.0, 26.0, 3.0, 0.5),
    "paprika":       (282, 54.0, 10.0, 14.0, 13.0, 2.1, 0.068),
    "garlic_powder": (331, 73.0, 2.5, 17.0, 0.7, 0.2, 0.06),
    "oj":            (45, 10.0, 8.0, 0.7, 0.2, 0.0, 0.001),
    "cold_brew":     (2, 0, 0, 0.1, 0, 0, 0.002),
    "kombucha":      (13, 3.0, 3.0, 0, 0, 0, 0.005),
    "sports_drink":  (19, 5.0, 5.0, 0, 0, 0, 0.041),
    "energy_drink":  (45, 11.0, 11.0, 0, 0, 0, 0.1),
    "slush":         (50, 13.0, 13.0, 0, 0, 0, 0.01),
    "sparkling":     (0, 0, 0, 0, 0, 0, 0),
    "pizza":         (268, 33.0, 3.6, 11.0, 10.0, 4.5, 0.6),
    "edamame":       (121, 9.0, 2.2, 12.0, 5.0, 0.6, 0.006),
    "berries":       (35, 8.0, 5.0, 0.7, 0.3, 0.0, 0.001),
    "ham":           (145, 1.5, 1.0, 21.0, 6.0, 2.0, 1.2),
    "hummus":        (166, 14.0, 0.3, 8.0, 10.0, 1.4, 0.38),
    "pesto":         (464, 6.0, 2.0, 5.0, 47.0, 7.0, 0.9),
    "trail_mix":     (462, 45.0, 30.0, 13.0, 29.0, 5.0, 0.1),
    "dark_chocolate": (546, 61.0, 48.0, 4.9, 31.0, 19.0, 0.024),
    "chips":         (536, 53.0, 0.3, 7.0, 34.0, 3.0, 0.5),
    "rice_cakes":    (387, 81.0, 0.9, 8.0, 2.8, 0.6, 0.03),
    "corn_nuts":     (446, 72.0, 1.0, 8.0, 14.0, 2.4, 0.66),
    "jerky":         (410, 11.0, 9.0, 33.0, 26.0, 11.0, 2.2),
    "sushi":         (150, 22.0, 3.0, 6.0, 3.5, 0.7, 0.35),
    "taquito":       (290, 28.0, 1.0, 9.0, 16.0, 5.0, 0.55),
    "whey":          (375, 8.0, 4.0, 75.0, 5.0, 2.0, 0.35),
    "casein":        (367, 7.0, 3.3, 80.0, 1.7, 1.0, 0.3),
    "protein_bar":   (400, 40.0, 20.0, 30.0, 13.0, 5.0, 0.3),
    "collagen":      (360, 0, 0, 90.0, 0, 0, 0.25),
    "creatine":      (0, 0, 0, 0, 0, 0, 0),
}


def _nutrients(key: str | None) -> dict | None:
    if key is None:
        return None
    kcal, carbs, sugars, protein, fat, satfat, sodium = _P[key]
    return {
        "energy-kcal_100g": kcal,
        "carbohydrates_100g": carbs,
        "sugars_100g": sugars,
        "proteins_100g": protein,
        "fat_100g": fat,
        "saturated-fat_100g": satfat,
        "sodium_100g": sodium,
    }


# item_name: (category, typical_unit_price, mode, package_oz, nutrient_profile)
#   mode "lb"  → sold by weight; the receipt line carries an explicit weight
#   mode "ea"  → discrete unit; package_oz (if set) feeds the size fallback
#   nutrient_profile None → item stays unmatched (feeds the X-Ray queue and
#   the "Missing USDA Data" slice — the transparency features need gaps too)
ITEM_CATALOG: dict[str, tuple[str, float, str, float | None, str | None]] = {
    # ---- Produce ----
    "Spotted Bananas":                       ("Produce", 0.27, "lb", None, "banana"),
    "Organicish Fuji Apples":                ("Produce", 1.39, "lb", None, "apple"),
    "Baby Spinach Situation 5oz":            ("Produce", 3.29, "ea", 5, "spinach"),
    "Perfectly Ripe Avocados 4pk":           ("Produce", 5.79, "ea", 24, "avocado"),
    "Suspiciously Round Tomatoes":           ("Produce", 4.19, "lb", None, "tomato"),
    "Broccoli Chunks":                       ("Produce", 1.69, "lb", None, "broccoli"),
    "Bag of Limes (Many)":                   ("Produce", 3.49, "ea", 16, None),
    "Gourmet Carrots 2lb":                   ("Produce", 1.99, "ea", 32, "carrot"),
    "Heirloom-Adjacent Peppers":             ("Produce", 2.99, "lb", None, "pepper"),

    # ---- Dairy ----
    "Whole Milk (The Good Kind) 64oz":       ("Dairy", 4.39, "ea", 64, "milk"),
    "Greek Yogurt Situation 32oz":           ("Dairy", 5.79, "ea", 32, "greek_yogurt"),
    "Cage-Ish Free Eggs 12ct":               ("Dairy", 4.89, "ea", 24, "eggs"),
    "Fancy Sharp Cheddar 2lb":               ("Dairy", 8.29, "ea", 32, "cheddar"),
    "Unsalted Fancy Butter 1lb":             ("Dairy", 5.19, "ea", 16, "butter"),
    "Oat Drink (Not Milk) 64oz":             ("Dairy", 5.99, "ea", 64, "oat_milk"),

    # ---- Meat & Seafood ----
    "Free-Range Chicken Breast":             ("Meat & Seafood", 6.89, "lb", None, "chicken"),
    "Beef That's Mostly Lean":               ("Meat & Seafood", 5.69, "lb", None, "beef"),
    "Brisket of Destiny":                    ("Meat & Seafood", 8.99, "lb", None, "beef"),
    "Lamb Chops (Special Occasion)":         ("Meat & Seafood", 14.99, "lb", None, "lamb"),
    "Salmon From The Ocean":                 ("Meat & Seafood", 9.89, "lb", None, "salmon"),
    "Big Shrimp (Frozen Bag) 2lb":           ("Meat & Seafood", 12.99, "ea", 32, "shrimp"),
    "Thicc-Cut Bacon 12oz":                  ("Meat & Seafood", 7.49, "ea", 12, "bacon"),
    "Protein Puck Burger Patties 2lb":       ("Meat & Seafood", 11.99, "ea", 32, "beef"),

    # ---- Bakery ----
    "Sourdough Vibes Loaf 24oz":             ("Bakery", 4.89, "ea", 24, "bread"),
    "Multigrain Everything Bagels 6ct":      ("Bakery", 3.39, "ea", 18, "bagel"),
    "Pretzel Buns (Fancy) 4pk":              ("Bakery", 3.99, "ea", 12, "bread"),
    "Croissants au Beurre 4ct":              ("Bakery", 6.49, "ea", 8, "croissant"),
    "Un Oeuf Already Baguette":              ("Bakery", 3.29, "ea", 10, "bread"),
    "Quiche Lorraine (Pun Included)":        ("Bakery", 8.99, "ea", 16, "quiche"),
    "Lemon Drizzle Bundt 28oz":              ("Bakery", 12.99, "ea", 28, "bundt"),
    "Chocolate Stout Bundt 28oz":            ("Bakery", 13.99, "ea", 28, "bundt"),
    "Mini Bundtlets 4pk":                    ("Bakery", 9.99, "ea", 16, "bundt"),
    "Strawberry Tartlette Flight 6ct":       ("Bakery", 11.49, "ea", 15, "tart"),
    "Tartan Plaid Shortbread Tin 12oz":      ("Bakery", 8.99, "ea", 12, "shortbread"),

    # ---- Pantry ----
    "Old-Fashioned Oats 42oz":               ("Pantry", 4.19, "ea", 42, "oats"),
    "Brown Rice (The Good One) 5lb":         ("Pantry", 6.39, "ea", 80, "rice"),
    "Quinoa (Pronounce At Own Risk) 4lb":    ("Pantry", 9.99, "ea", 64, "quinoa"),
    "Flour, All-Purpose-ish 5lb":            ("Pantry", 4.29, "ea", 80, "flour"),
    "Extra Virginal Olive Oil 25oz":         ("Pantry", 10.79, "ea", 25, "olive_oil"),
    "Beans (Black, Canned) 15oz":            ("Pantry", 1.19, "ea", 15, "black_beans"),
    "Penne Pasta 1lb":                       ("Pantry", 1.69, "ea", 16, "pasta"),
    "Tomato Sauce Classic 24oz":             ("Pantry", 3.89, "ea", 24, "tomato_sauce"),
    "Suspiciously Delicious Almond Butter 16oz": ("Pantry", 9.29, "ea", 16, "almond_butter"),
    "Coconut Aminos (Fancy Soy Sauce) 10oz": ("Pantry", 5.99, "ea", 10, None),
    "Raspberry Web Jam 10oz":                ("Pantry", 6.49, "ea", 10, "jam"),

    # ---- Salsa Emporium exclusives ----
    "Salsa Verde Vortex 16oz":               ("Pantry", 4.99, "ea", 16, "salsa"),
    "Mango Habanero Situation 16oz":         ("Pantry", 5.49, "ea", 16, "salsa"),
    "Salsa Roja: The Original 24oz":         ("Pantry", 6.49, "ea", 24, "salsa"),
    "Ghost Pepper Regret Sauce 5oz":         ("Pantry", 7.99, "ea", 5, "hot_sauce"),
    "Restaurant-Style Tortilla Chips 20oz":  ("Snacks", 4.79, "ea", 20, "tortilla_chips"),
    "Queso For One (Jumbo) 15oz":            ("Snacks", 6.99, "ea", 15, "queso"),

    # ---- B2BSaasoons (seasonings, enterprise pricing) ----
    "Smoked Paprika (Enterprise Tier) 4oz":  ("Pantry", 6.99, "ea", 4, "paprika"),
    "Everything Bagel Seasoning API 6oz":    ("Pantry", 5.49, "ea", 6, None),
    "Garlic Powder (Per-Seat License) 8oz":  ("Pantry", 4.99, "ea", 8, "garlic_powder"),
    "Cumin Subscription Refill 3oz":         ("Pantry", 3.99, "ea", 3, None),
    "Taco Seasoning SLA 1oz":                ("Pantry", 1.49, "ea", 1, None),
    "Cinnamon Sticks (Annual Contract) 2oz": ("Pantry", 4.49, "ea", 2, None),

    # ---- Beverages ----
    "Bubbly Water 12pk":                     ("Beverages", 5.89, "ea", 144, "sparkling"),
    "OJ (With Pulp) 52oz":                   ("Beverages", 4.89, "ea", 52, "oj"),
    "Cold Brew Concentrate 32oz":            ("Beverages", 7.39, "ea", 32, "cold_brew"),
    "Funky Fermented Tea 16oz":              ("Beverages", 3.69, "ea", 16, "kombucha"),
    "Electrolyte Drink (Melon) 20oz":        ("Beverages", 2.49, "ea", 20, "sports_drink"),

    # ---- LuridLurie's Gas ----
    "Gas Station Sushi (Brave) 8oz":         ("Deli", 6.99, "ea", 8, "sushi"),
    "Neon Energy Sludge 16oz":               ("Beverages", 3.49, "ea", 16, "energy_drink"),
    "Mystery Meat Stick 1.5oz":              ("Snacks", 2.29, "ea", 1.5, "jerky"),
    "Taquito of the Ancients":               ("Snacks", 2.99, "ea", 4, "taquito"),
    "Slush Dimension Blue Raspberry 32oz":   ("Beverages", 2.49, "ea", 32, "slush"),
    "Road Trip Corn Nuts 4oz":               ("Snacks", 1.79, "ea", 4, "corn_nuts"),
    "Scratcher-Adjacent Gum":                ("Snacks", 1.99, "ea", None, None),

    # ---- Frozen ----
    "Margherita Pizza (Fancy) 14oz":         ("Frozen", 7.89, "ea", 14, "pizza"),
    "Edamame Beans 2lb":                     ("Frozen", 5.39, "ea", 32, "edamame"),
    "Mixed Berries Big Bag 3lb":             ("Frozen", 8.89, "ea", 48, "berries"),
    "Cauliflower Crust Pizza 11oz":          ("Frozen", 8.49, "ea", 11, "pizza"),

    # ---- Deli ----
    "Fancy Ham Slices 6oz":                  ("Deli", 5.89, "ea", 6, "ham"),
    "Hummus Original 17oz":                  ("Deli", 4.39, "ea", 17, "hummus"),
    "Pesto Situation 7oz":                   ("Deli", 5.49, "ea", 7, "pesto"),

    # ---- Snacks ----
    "Artisanal Trail Mix 1lb":               ("Snacks", 7.39, "ea", 16, "trail_mix"),
    "Very Dark Chocolate 3.5oz":             ("Snacks", 2.89, "ea", 3.5, "dark_chocolate"),
    "Sea Salt Kettle Chips 8oz":             ("Snacks", 4.19, "ea", 8, "chips"),
    "Rice Cakes (Plain Sadness) 4oz":        ("Snacks", 3.29, "ea", 4, "rice_cakes"),

    # ---- Peptide Inferance Exchange ----
    "Whey Protein: Vanilla Hypothesis 2lb":  ("Health & Beauty", 34.99, "ea", 32, "whey"),
    "Casein Nocturne 2lb":                   ("Health & Beauty", 39.99, "ea", 32, "casein"),
    "Creatine Monohydrate (Peer-Reviewed) 10oz": ("Health & Beauty", 24.99, "ea", 10, "creatine"),
    "Inference-Grade Protein Bars 12ct":     ("Health & Beauty", 26.99, "ea", 25, "protein_bar"),
    "Collagen Peptides (Skeptical) 16oz":    ("Health & Beauty", 27.99, "ea", 16, "collagen"),
    "Electrolyte Powder (Citrus Consensus) 12oz": ("Health & Beauty", 19.99, "ea", 12, None),

    # ---- Health & Beauty (general) ----
    "Vitamin D (Sunshine in a Pill)":        ("Health & Beauty", 12.79, "ea", None, None),
    "Floss Picks 150ct":                     ("Health & Beauty", 4.89, "ea", None, None),
    "Melatonin 5mg 60ct":                    ("Health & Beauty", 8.99, "ea", None, None),

    # ---- Household ----
    "Dish Soap (Lemon-ish) 32oz":            ("Household", 4.89, "ea", None, None),
    "Paper Towels (Strong) 6-Roll":          ("Household", 9.89, "ea", None, None),
    "Laundry Detergent (Mountain Myth)":     ("Household", 14.79, "ea", None, None),
    "Sponges (Fancy) 6pk":                   ("Household", 4.49, "ea", None, None),
}

# Which stores stock which items. Staples overlap across the big stores so
# the store-comparison charts ("Identical Item Store Diff") have material.
STORE_CATALOG: dict[str, list[str]] = {
    "VendorVics": [
        "Spotted Bananas", "Organicish Fuji Apples", "Broccoli Chunks",
        "Whole Milk (The Good Kind) 64oz", "Cage-Ish Free Eggs 12ct",
        "Unsalted Fancy Butter 1lb", "Beef That's Mostly Lean",
        "Sourdough Vibes Loaf 24oz", "Old-Fashioned Oats 42oz",
        "Beans (Black, Canned) 15oz", "Penne Pasta 1lb", "Tomato Sauce Classic 24oz",
        "OJ (With Pulp) 52oz", "Bubbly Water 12pk", "Margherita Pizza (Fancy) 14oz",
        "Sea Salt Kettle Chips 8oz", "Dish Soap (Lemon-ish) 32oz",
        "Paper Towels (Strong) 6-Roll", "Laundry Detergent (Mountain Myth)",
    ],
    "SpaceWay": [
        "Spotted Bananas", "Organicish Fuji Apples", "Baby Spinach Situation 5oz",
        "Suspiciously Round Tomatoes", "Gourmet Carrots 2lb",
        "Whole Milk (The Good Kind) 64oz", "Greek Yogurt Situation 32oz",
        "Cage-Ish Free Eggs 12ct", "Fancy Sharp Cheddar 2lb",
        "Free-Range Chicken Breast", "Big Shrimp (Frozen Bag) 2lb",
        "Multigrain Everything Bagels 6ct", "Penne Pasta 1lb",
        "Tomato Sauce Classic 24oz", "Flour, All-Purpose-ish 5lb",
        "Electrolyte Drink (Melon) 20oz", "Bubbly Water 12pk",
        "Cauliflower Crust Pizza 11oz", "Edamame Beans 2lb",
        "Hummus Original 17oz", "Rice Cakes (Plain Sadness) 4oz",
        "Vitamin D (Sunshine in a Pill)", "Melatonin 5mg 60ct",
        "Sponges (Fancy) 6pk",
    ],
    "WhollyFUD": [
        "Organicish Fuji Apples", "Baby Spinach Situation 5oz",
        "Perfectly Ripe Avocados 4pk", "Heirloom-Adjacent Peppers",
        "Gourmet Carrots 2lb", "Greek Yogurt Situation 32oz",
        "Oat Drink (Not Milk) 64oz", "Unsalted Fancy Butter 1lb",
        "Free-Range Chicken Breast", "Salmon From The Ocean",
        "Extra Virginal Olive Oil 25oz", "Quinoa (Pronounce At Own Risk) 4lb",
        "Suspiciously Delicious Almond Butter 16oz",
        "Coconut Aminos (Fancy Soy Sauce) 10oz", "Cold Brew Concentrate 32oz",
        "Funky Fermented Tea 16oz", "Mixed Berries Big Bag 3lb",
        "Pesto Situation 7oz", "Very Dark Chocolate 3.5oz",
        "Artisanal Trail Mix 1lb", "Floss Picks 150ct",
    ],
    "MeatBagFuels": [
        "Free-Range Chicken Breast", "Beef That's Mostly Lean",
        "Brisket of Destiny", "Lamb Chops (Special Occasion)",
        "Salmon From The Ocean", "Big Shrimp (Frozen Bag) 2lb",
        "Thicc-Cut Bacon 12oz", "Protein Puck Burger Patties 2lb",
        "Fancy Ham Slices 6oz", "Cage-Ish Free Eggs 12ct",
    ],
    "Salsa Emporium": [
        "Salsa Verde Vortex 16oz", "Mango Habanero Situation 16oz",
        "Salsa Roja: The Original 24oz", "Ghost Pepper Regret Sauce 5oz",
        "Restaurant-Style Tortilla Chips 20oz", "Queso For One (Jumbo) 15oz",
        "Bag of Limes (Many)",
    ],
    "The FeedLoft": [
        "Old-Fashioned Oats 42oz", "Brown Rice (The Good One) 5lb",
        "Quinoa (Pronounce At Own Risk) 4lb", "Flour, All-Purpose-ish 5lb",
        "Extra Virginal Olive Oil 25oz", "Beans (Black, Canned) 15oz",
        "Suspiciously Delicious Almond Butter 16oz", "Bubbly Water 12pk",
        "OJ (With Pulp) 52oz", "Mixed Berries Big Bag 3lb",
        "Fancy Sharp Cheddar 2lb", "Big Shrimp (Frozen Bag) 2lb",
        "Artisanal Trail Mix 1lb", "Paper Towels (Strong) 6-Roll",
        "Laundry Detergent (Mountain Myth)", "Sponges (Fancy) 6pk",
        "Floss Picks 150ct",
    ],
    "B2BSaasoons": [
        "Smoked Paprika (Enterprise Tier) 4oz", "Everything Bagel Seasoning API 6oz",
        "Garlic Powder (Per-Seat License) 8oz", "Cumin Subscription Refill 3oz",
        "Taco Seasoning SLA 1oz", "Cinnamon Sticks (Annual Contract) 2oz",
    ],
    "LuridLurie's Gas": [
        "Gas Station Sushi (Brave) 8oz", "Neon Energy Sludge 16oz",
        "Mystery Meat Stick 1.5oz", "Taquito of the Ancients",
        "Slush Dimension Blue Raspberry 32oz", "Road Trip Corn Nuts 4oz",
        "Scratcher-Adjacent Gum", "Electrolyte Drink (Melon) 20oz",
    ],
    "Tartanula's": [
        "Strawberry Tartlette Flight 6ct", "Tartan Plaid Shortbread Tin 12oz",
        "Raspberry Web Jam 10oz", "Very Dark Chocolate 3.5oz",
    ],
    "L'UnOeufPun Bakery": [
        "Croissants au Beurre 4ct", "Un Oeuf Already Baguette",
        "Quiche Lorraine (Pun Included)", "Sourdough Vibes Loaf 24oz",
        "Multigrain Everything Bagels 6ct", "Pretzel Buns (Fancy) 4pk",
        "Cage-Ish Free Eggs 12ct",
    ],
    "Peptide Inferance Exchange": [
        "Whey Protein: Vanilla Hypothesis 2lb", "Casein Nocturne 2lb",
        "Creatine Monohydrate (Peer-Reviewed) 10oz",
        "Inference-Grade Protein Bars 12ct", "Collagen Peptides (Skeptical) 16oz",
        "Electrolyte Powder (Citrus Consensus) 12oz",
    ],
    "BundtCake & More": [
        "Lemon Drizzle Bundt 28oz", "Chocolate Stout Bundt 28oz",
        "Mini Bundtlets 4pk",
    ],
}


def vary(price: float, pct: float = 0.09) -> float:
    """Apply small random price variation to simulate real-world price changes."""
    return round(price * random.uniform(1 - pct, 1 + pct), 2)


def build_schedule() -> list[tuple[str, date, list[str]]]:
    """Return list of (store_name, purchase_date, [item_names])."""
    today = date.today()
    schedule = []

    def trips(store: str, weeks: list[float], k_min: int, k_max: int):
        catalog = STORE_CATALOG[store]
        for w in weeks:
            d = today - timedelta(weeks=w, days=random.randint(0, 2))
            k = min(len(catalog), random.randint(k_min, k_max))
            schedule.append((store, d, random.sample(catalog, k=k)))

    # SpaceWay is the routine weekly store
    trips("SpaceWay", [15, 13, 12, 10, 9, 7, 6, 4, 3, 1], 6, 12)
    # VendorVics bi-weekly budget runs
    trips("VendorVics", [14, 12, 10, 8, 6, 4, 2], 5, 10)
    # WhollyFUD premium trips
    trips("WhollyFUD", [13, 9, 5, 2], 5, 9)
    # MeatBagFuels protein restocks
    trips("MeatBagFuels", [12, 9, 6, 3, 1], 3, 6)
    # The FeedLoft monthly bulk hauls
    trips("The FeedLoft", [13, 8, 4], 8, 13)
    # LuridLurie's Gas — impulse stops
    trips("LuridLurie's Gas", [11, 8, 6, 4, 2, 0.5], 1, 4)
    # Salsa Emporium pilgrimages
    trips("Salsa Emporium", [10, 5, 1], 3, 6)
    # L'UnOeufPun weekend pastry runs
    trips("L'UnOeufPun Bakery", [9, 7, 5, 3, 1], 2, 5)
    # Tartanula's, BundtCake — occasional dessert emergencies
    trips("Tartanula's", [8, 2], 2, 4)
    trips("BundtCake & More", [6, 1], 1, 3)
    # Peptide Inferance Exchange — online supplement orders
    trips("Peptide Inferance Exchange", [12, 7, 2], 2, 4)
    # B2BSaasoons — quarterly seasoning procurement
    trips("B2BSaasoons", [11, 3], 3, 6)

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
        nutrient_count = 0
        for item_name, (cat_name, _, _, _, profile) in ITEM_CATALOG.items():
            existing = db.query(Item).filter(Item.name == item_name).first()
            if existing:
                item_obj_map[item_name] = existing
                continue
            nutrients = _nutrients(profile)
            if nutrients:
                nutrient_count += 1
            item_obj = Item(
                name=item_name,
                normalized_name=item_name.lower(),
                category_id=cat_map[cat_name].id,
                nutrients=nutrients,
                nutrition_source="demo" if nutrients else None,
            )
            db.add(item_obj)
            db.flush()
            item_obj_map[item_name] = item_obj
        print(f"  ✓ {len(ITEM_CATALOG)} items in catalog ({nutrient_count} with nutrition data)")

        # ---- Receipts & ReceiptItems ----
        schedule = build_schedule()
        receipt_count = 0
        receipt_item_count = 0

        for store_name, receipt_date, item_names in schedule:
            store = store_map[store_name]

            line_items_data = []
            total_amount = 0.0

            for item_name in item_names:
                cat_name, base_price, mode, pkg_oz, _profile = ITEM_CATALOG[item_name]
                unit_price = vary(base_price)

                if mode == "lb":
                    # Sold by weight: the line carries an explicit weight in lb
                    weight_lb = round(random.uniform(0.8, 2.5), 2)
                    qty = 1.0
                    line_total = round(unit_price * weight_lb, 2)
                    line_weight, line_weight_unit = weight_lb, "lb"
                else:
                    qty = float(random.choice([1, 1, 1, 2]))
                    line_total = round(unit_price * qty, 2)
                    # Package size (if known) recorded as total purchased weight
                    if pkg_oz:
                        line_weight, line_weight_unit = round(pkg_oz * qty, 2), "oz"
                    else:
                        line_weight, line_weight_unit = None, None

                total_amount += line_total
                line_items_data.append({
                    "name": item_name,
                    "quantity": qty,
                    "unit_price": unit_price,
                    "total": line_total,
                    "unit_type": line_weight_unit or "ea",
                    "weight": line_weight,
                    "category": cat_name,
                })

            total_amount = round(total_amount, 2)

            receipt = Receipt(
                store_id=store.id,
                purchase_date=datetime.combine(receipt_date, datetime.min.time()),
                total_amount=total_amount,
                status="completed",
                notes="DEMO_DATA",
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
                    weight=li["weight"],
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
