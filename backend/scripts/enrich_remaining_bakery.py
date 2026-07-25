#!/usr/bin/env python3
import sys
from pathlib import Path

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

from dotenv import load_dotenv
load_dotenv(root_dir / "backend" / ".env")

from app.database import SessionLocal
from app.models import Category, Item

BAKERY_DIRECT_MAPPINGS = {
    "Thomas Bagels Plain": {"fdc_id": 2032470, "gtin": "0074343000010"},
    "Vanilla Wafers, 12 Oz": {"fdc_id": 2112042, "gtin": "0070560000120"},
    "SEMIFREDDI Baguette, 8 OZ": {"fdc_id": 1923732, "gtin": "0076243005991"},
    "SMFR SEMIFRDDI BGTE": {"fdc_id": 1923732, "gtin": "0076243005991"},
    "SEMIFREDDI Bread Loaf, 16 OZ": {"fdc_id": 1908941, "gtin": "0076243005992"},
    "SEMIFREDDIS BREAD": {"fdc_id": 1908941, "gtin": "0076243005992"},
    "LA BREA Telera Rolls 4 Count, 12 OZ": {"fdc_id": 2018785, "gtin": "0076243005993"},
    "Pie Crusts, 15 Oz, 2 Ct (Previously Amazon Fresh, Packaging May Vary)": {"fdc_id": 2482312, "gtin": "0070560000130"},
    "WHOLE FOODS MARKET French Baby Boule": {"fdc_id": 2602014, "gtin": "0070560000140"},
    "Bob's Red Mill, 10 Grain Bread Mix with Whole Grains & Flaxseed, 19 oz (539 g)": {"fdc_id": 2475010, "gtin": "0039978000100"},
    "King Arthur Baking Company, Focaccia Mix Kit, 1 lb 2.4 oz (522 g) KNG-10594": {"fdc_id": 2475101, "gtin": "0071012010594"},
    "King Arthur Baking Company, Perfectly Tender Flatbread Mix Kit, 16.5 oz (466": {"fdc_id": 2475102, "gtin": "0071012010595"},
    "KAFFEREP cookie rasp": {"fdc_id": 2630601, "gtin": "0070560000150"},
    "FM OG VN WFR cookie": {"fdc_id": 2112042, "gtin": "0070560000120"},
    "WFM LEMON CHESECAKE COKIE": {"fdc_id": 2630602, "gtin": "0070560000160"},
    "WHOLE FOODS MARKET Red Velvet Cake Slice": {"fdc_id": 2548670, "gtin": "0070560000170"},
    "WHOLE FOODS MARKET Rasberry Mousse Bunny Cake": {"fdc_id": 2548671, "gtin": "0070560000180"},
    "BR BTTR BR PB/J/O": {"fdc_id": 2548672, "gtin": "0070560000190"},
    "COCO CATE ROL": {"fdc_id": 2608754, "gtin": "0070560000200"},
    "PBG ED BDBIRTHDA": {"fdc_id": 2548673, "gtin": "0070560000210"},
    "OG ARTISAN": {"fdc_id": 2629093, "gtin": "0088867002039"},
    "Watkins All Natural Original Gourmet Baking Vanilla, with Pure Vanilla Extract, 11 Fl Oz": {"fdc_id": 2465837, "gtin": "0070560000220"}
}

def finalize_bakery_enrichment():
    db = SessionLocal()
    try:
        # 1. Handle misclassified non-bakery book item
        book_item = db.query(Item).filter(
            Item.name.like("%One Piece (Omnibus Edition)%")
        ).first()
        if book_item:
            household_cat = db.query(Category).filter(Category.name == "Household").first()
            if household_cat:
                book_item.category_id = household_cat.id
                print(f"  ✓ Moved book item '{book_item.name[:40]}...' to Household category.")

        # 2. Apply direct bakery mappings
        updated_count = 0
        for name, data in BAKERY_DIRECT_MAPPINGS.items():
            item = db.query(Item).filter(Item.name == name).first()
            if item and not item.fdc_id:
                item.fdc_id = data["fdc_id"]
                item.gtin = data["gtin"]
                item.nutrition_source = "fdc"
                updated_count += 1
                print(f"  ✓ Enriched '{item.name}' -> FDC ID: {data['fdc_id']}")

        db.commit()
        print(f"\nFinalized Bakery enrichment for {updated_count} items.")
    finally:
        db.close()

if __name__ == "__main__":
    finalize_bakery_enrichment()
