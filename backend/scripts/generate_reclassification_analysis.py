#!/usr/bin/env python3
import sys
import re
from pathlib import Path

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

from dotenv import load_dotenv
load_dotenv(root_dir / "backend" / ".env")

from app.database import SessionLocal
from app.models import Category, Item

RULES = [
    ("Bakery", [r"\btelera\b", r"\bfocaccia\b", r"\bbread\b", r"\bbaguette\b", r"\bbun\b", r"\bcake\b", r"\blavash\b", r"\bboule\b", r"\brolls\b"]),
    ("Beverages", [r"\bathletic brewing\b", r"\bnon-alcoholic\b", r"\blager\b", r"\bbrut\b", r"\brosé\b", r"\brose wine\b", r"\bblanc de blancs\b", r"\bmontepulciano\b", r"\bchandon\b", r"\bjust the haze\b", r"\bkombucha\b", r"\bkom ber lem\b", r"\bjuice\b", r"\bsoda\b", r"\bwine\b", r"\bbeer\b", r"\bwater\b", r"\btea\b", r"\bcoffee\b"]),
    ("Dairy", [r"\bcheddar\b", r"\bcheese\b", r"\btzatziki\b", r"\bqueso\b", r"\bmahon\b", r"\bsmoothie\b", r"\bmilk\b", r"\byogurt\b", r"\bbutter\b", r"\bcreamer\b", r"\bskyr\b", r"\bcottage\b"]),
    ("Produce", [r"\bromaine\b", r"\bblackberries\b", r"\bcauliflower\b", r"\bblueberry\b", r"\bblueberries\b", r"\bstrawberries\b", r"\btulips\b", r"\bbouquet\b", r"\bbanana\b", r"\bapple\b", r"\bcarrot\b", r"\btomato\b", r"\bpotato\b", r"\bonion\b", r"\bavocado\b", r"\bnectarine\b", r"\bgarlic\b", r"\bkale\b", r"\blime\b", r"\bpear\b"]),
    ("Meat", [r"\bground turkey\b", r"\bham\b", r"\bmackerel\b", r"\bsausage\b", r"\bchicken\b", r"\bbeef\b", r"\bpork\b", r"\blamb\b", r"\bsalmon\b", r"\bshrimp\b", r"\bbanger\b", r"\bfranks\b", r"\bmeatballs\b"]),
    ("Frozen", [r"\bfreezer pops\b", r"\bjack wings\b", r"\bjack nuggets\b", r"\bfries\b", r"\bfrozen\b", r"\bice cream\b", r"\bgoodpop\b"]),
    ("Pantry", [r"\bspaghetti\b", r"\bpassata\b", r"\bmiso\b", r"\bmuesli\b", r"\bwheat germ\b", r"\bspecial k\b", r"\bflour\b", r"\bbaking powder\b", r"\bpaprika\b", r"\bmustard\b", r"\bvinegar\b", r"\byeast\b", r"\bseasoning\b", r"\bcanned\b", r"\bnoodle\b", r"\brice\b", r"\bbeans\b"]),
    ("Snacks", [r"\bcroccantini\b", r"\bsesame sticks\b", r"\bred vines\b", r"\bcandy\b", r"\bchocolate\b", r"\bpopcorn\b", r"\bcracker\b", r"\bcrackers\b", r"\bchips?\b"]),
    ("Health & Beauty", [r"\blevothyroxin\b", r"\botc\b", r"\bgaba\b", r"\bdigest\b", r"\bcapsules\b", r"\bashwagandha\b", r"\blip balm\b", r"\bnitrile\b", r"\bacne wash\b"]),
    ("Fees & Taxes", [r"\bcrv\b", r"\bdeposit\b", r"\bfee\b", r"\btax\b", r"\btotal\b", r"\brefund\b", r"\bsan francisco\b", r"\bewr to nwk\b", r"\bsavings\b", r"dept#"]),
    ("Household", [r"\bballoon\b", r"\bbanner\b", r"\bwire cup\b", r"\bgasoline\b", r"\btobacc\b", r"\bcandle\b", r"\bhand soap\b", r"\bfoil\b", r"\bjersey\b", r"\btrack jacket\b", r"\bshin guard\b", r"\bbio tub\b"]),
]

def classify_item(name: str):
    norm = name.strip().lower()
    for cat, patterns in RULES:
        for p in patterns:
            if re.search(p, norm):
                if cat == "Produce" and any(w in norm for w in ["romaine", "blackberries", "cauliflower", "blueberry", "strawberries"]):
                    return cat, "100 %"
                elif cat == "Meat" and any(w in norm for w in ["turkey", "ham", "beef", "chicken"]):
                    return cat, "100 %"
                elif cat == "Beverages" and any(w in norm for w in ["wine", "brut", "chandon", "montepulciano", "non-alcoholic"]):
                    return cat, "95 %"
                elif cat == "Dairy" and any(w in norm for w in ["cheddar", "cheese", "milk", "yogurt"]):
                    return cat, "95 %"
                elif cat == "Fees & Taxes" and any(w in norm for w in ["crv", "tax", "deposit"]):
                    return cat, "95 %"
                elif cat == "Snacks" and any(w in norm for w in ["red vines", "croccantini", "sesame sticks"]):
                    return cat, "95 %"
                elif cat == "Pantry" and any(w in norm for w in ["spaghetti", "passata", "special k"]):
                    return cat, "95 %"
                elif cat == "Frozen" and any(w in norm for w in ["freezer pops", "goodpop"]):
                    return cat, "95 %"
                return cat, "85 %"
    return "Other", "50 %"

def generate_analysis():
    db = SessionLocal()
    try:
        other_cat = db.query(Category).filter(Category.name == "Other").first()
        if not other_cat:
            print("Error: 'Other' category not found in database.")
            return

        items = db.query(Item).filter(Item.category_id == other_cat.id).all()
        print(f"Found {len(items)} items in 'Other' category.")

        results = []
        for item in items:
            proposed_cat, conf = classify_item(item.name)
            results.append((item.name, "Other", proposed_cat, conf))

        # Sort alphabetically by Proposed Category then Item Name
        results.sort(key=lambda x: (x[2], x[0]))

        lines = ["# Item Reclassification Analysis\n"]
        lines.append("| Item Name | Current Category | Proposed Category | Confidence |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for item_name, cur_cat, prop_cat, conf in results:
            lines.append(f"| {item_name} | {cur_cat} | {prop_cat} | {conf} |")

        output_path = root_dir / "reclassification_analysis.md"
        output_path.write_text("\n".join(lines) + "\n")
        print(f"Successfully generated {output_path} with {len(results)} item entries.")
    finally:
        db.close()

if __name__ == "__main__":
    generate_analysis()
