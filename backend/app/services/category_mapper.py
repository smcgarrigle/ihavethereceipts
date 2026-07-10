CATEGORY_MAP = {
    # OpenFoodFacts & Foreign Languages
    "en:hummus": "Deli",
    "en: half milk and half cream": "Dairy",
    "растителни храни и напитки": "Produce",  # Plant based foods
    "boissons et préparations de boissons": "Beverages",
    "aliments et boissons à base de végétaux": "Produce",
    "vleesproducten": "Meat",
    "condimentos": "Pantry",
    "plant-based foods and beverages": "Produce",
    "plant-based foods": "Produce",
    "salted snacks": "Snacks",
    "meats and their products": "Meat",
    "farming products": "Produce",
    "dairies": "Dairy",
    "null": "Other",
    "undefined": "Other",
    "food additives": "Other",
    "fats": "Pantry",
    "meals": "Deli",
    "rice dishes": "Pantry",
    "fruit sodas": "Beverages",
    "baking decorations": "Bakery",
    "beverages and beverages preparations": "Beverages",
    "bread": "Bakery",
    "snacks": "Snacks",
    "chips and fries": "Snacks",
    "100 grass fed angus beef": "Meat",
    "rice": "Pantry",
    "cabbages": "Produce",
    "seafood": "Meat",
    "eggs": "Dairy",
    "desserts": "Bakery",
    "frozen foods": "Frozen",
    # USDA FDC Categories
    "frozen poultry, chicken & turkey": "Frozen",
    "snack, energy & granola bars": "Snacks",
    "chips, pretzels & snacks": "Snacks",
    "wholesome snacks": "Snacks",
    "pickles, olives, peppers & relishes": "Pantry",
    "meat/poultry/other animals - prepared/processed": "Meat",
    "meat/poultry/other animals  unprepared/unprocessed": "Meat",
    "processed cereal products": "Pantry",
    "bacon, sausages & ribs": "Meat",
    "frozen appetizers & hors d'oeuvres": "Frozen",
    "mexican dinner mixes": "Pantry",
    "popcorn, peanuts, seeds & related snacks": "Snacks",
    "canned vegetables": "Pantry",
    "cheese": "Dairy",
    "yogurt/yogurt substitutes": "Dairy",
    "milk/milk substitutes": "Dairy",
    "fruit & vegetable juice, nectars & fruit drinks": "Beverages",
    "water": "Beverages",
    "soda": "Beverages",
    "other drinks": "Beverages",
    "cookies & biscuits": "Bakery",
    "crusts & dough": "Bakery",
    "frozen dinners & entrees": "Frozen",
    "condiments": "Pantry",
    "sauces/spreads/dips/condiments": "Pantry",
    "crackers & biscotti": "Pantry",
    "dips & salsa": "Pantry",
    "ice cream & frozen yogurt": "Frozen",
    "other snacks": "Snacks",
    "pre-packaged fruit & vegetables": "Produce",
    "frozen fruit & fruit juice concentrates": "Frozen",
    "seasoning mixes, salts, marinades & tenderizers": "Pantry",
    "cereal": "Pantry",
    "eggs & egg substitutes": "Dairy",
    "frozen vegetables": "Frozen",
    "nut & seed butters": "Pantry",
    "flours & corn meal": "Pantry",
    "milk": "Dairy",
    "tomatoes": "Produce",
    "breads & buns": "Bakery",
    "frozen bread & dough": "Frozen",
    "baking additives & extracts": "Pantry",
    "biscuits/cookies": "Bakery",
    "fish & seafood": "Meat",
    "poultry, chicken & turkey": "Meat",
    "other deli": "Deli",
    "sausages, hotdogs & brats": "Meat",
    "other meats": "Meat",
    "jam, jelly & fruit spreads": "Pantry",
    "candy": "Snacks",
    "other grains & seeds": "Pantry",
    "vegetables - prepared/processed": "Produce",
    "canned seafood": "Meat",
    "butter & spread": "Dairy",
    "yogurt": "Dairy",
    "prepared pasta & pizza sauces": "Pantry",
    "prepared soups": "Pantry",
    "canned & bottled beans": "Pantry",
    "vegetable and lentil mixes": "Pantry",
    "frozen fish & seafood": "Frozen",
    "baking decorations & dessert toppings": "Bakery",
    "herbs & spices": "Pantry",
    "cooked & prepared": "Deli",
    "tea bags": "Beverages",
    "deli salads": "Deli",
    "oriental, mexican & ethnic sauces": "Pantry",
    "gelatin, gels, pectins & desserts": "Bakery",
    "cake, cookie & cupcake mixes": "Bakery",
    "chocolate": "Snacks",
    "frozen prepared sides": "Frozen",
    "bread & muffin mixes": "Bakery",
    "canned fruit": "Pantry",
    "other cooking sauces": "Pantry",
    "iced & bottle tea": "Beverages",
    "chili & stew": "Pantry",
    "prepared wraps and burittos": "Deli",
    "powdered drinks": "Beverages",
    "non alcoholic beverages - not ready to drink": "Beverages",
    "non alcoholic beverages  ready to drink": "Beverages",
    "salad dressing & mayonnaise": "Pantry",
    "other soups": "Pantry",
    "grain based products / meals": "Pantry",
    "vegetable & cooking oils": "Pantry",
    "other frozen desserts": "Frozen",
    "baby/infant - foods/beverages": "Other",
    "cakes, cupcakes, snack cakes": "Bakery",
    "ketchup, mustard, bbq & cheese sauce": "Pantry",
    "frozen patties and burgers": "Frozen",
    "french fries, potatoes & onion rings": "Frozen",
    "frozen bacon, sausages & ribs": "Frozen",
    "cream": "Dairy",
    "meal replacement supplements": "Health & Beauty",
    "pasta by shape & type": "Pantry",
    "vegetarian frozen meats": "Frozen",
    "fruit - prepared/processed": "Produce",
    "confectionery products": "Snacks",
}


# The strict master taxonomy. Every category resolution funnels into one of
# these — external/AI names never become new Category rows (the source of the
# 100+ fragmented-category problem this replaces).
CANONICAL_CATEGORIES = [
    "Produce",
    "Meat",
    "Dairy",
    "Bakery",
    "Deli",
    "Pantry",
    "Snacks",
    "Beverages",
    "Frozen",
    "Household",
    "Health & Beauty",
    "Fees & Taxes",
    "Other",
]

# Keyword fallback for names not in CATEGORY_MAP; first hit wins, so more
# specific groups come first (frozen/fees before generic food words).
_KEYWORD_RULES = [
    ("Frozen", ["frozen", "ice cream", "popsicle"]),
    ("Fees & Taxes", ["fee", "tax", "crv", "deposit", "surcharge"]),
    ("Health & Beauty", ["vitamin", "supplement", "shampoo", "toothpaste", "medicine",
                         "health", "beauty", "lotion", "deodorant"]),
    ("Household", ["household", "paper towel", "toilet", "detergent", "cleaner",
                   "trash", "foil", "batteries", "soap"]),
    ("Meat", ["meat", "beef", "pork", "chicken", "turkey", "poultry", "seafood",
              "fish", "sausage", "bacon", "jerky", "salmon", "shrimp", "lamb"]),
    ("Dairy", ["milk", "cheese", "yogurt", "butter", "cream", "egg", "dairy", "kefir"]),
    ("Bakery", ["bread", "baguette", "bakery", "cake", "cookie", "muffin", "dough",
                "tortilla", "bagel", "pastr", "croissant", "pie"]),
    ("Beverages", ["juice", "drink", "soda", "tea", "coffee", "water", "cola",
                   "beverage", "smoothie", "kombucha", "lemonade", "beer", "wine",
                   "alcohol", "cider"]),
    ("Snacks", ["snack", "chip", "candy", "chocolate", "popcorn", "cracker",
                "pretzel", "granola bar", "gum", "confection"]),
    ("Produce", ["fruit", "vegetable", "produce", "banana", "berr", "tomato",
                 "potato", "onion", "avocado", "salad", "greens", "herb", "mushroom"]),
    ("Deli", ["deli", "prepared", "hummus", "wrap", "sandwich", "sushi", "salami",
              "pepperoni", "cold cut", "charcuterie"]),
    ("Pantry", ["sauce", "spice", "condiment", "oil", "pasta", "rice", "cereal",
                "flour", "sugar", "canned", "soup", "bean", "spread", "jam",
                "dressing", "seasoning", "baking", "mix", "grain", "nut", "seed",
                "honey", "syrup", "broth", "stock", "pickle", "olive", "dip", "pesto"]),
]


def map_category_name(raw_name: str) -> str:
    """Resolve any raw category name (USDA, OpenFoodFacts, AI) to a canonical
    master category. Unknown names fall back to "Other" — they never leak
    through as new categories.
    """
    if not raw_name:
        return "Other"

    normalized = raw_name.strip().lower()

    # Already canonical (case-insensitive)?
    for canonical in CANONICAL_CATEGORIES:
        if normalized == canonical.lower():
            return canonical

    if normalized in CATEGORY_MAP:
        return CATEGORY_MAP[normalized]

    for canonical, keywords in _KEYWORD_RULES:
        if any(kw in normalized for kw in keywords):
            return canonical

    return "Other"
