from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Receipt
from app.services.nutrition_utils import calculate_receipt_item_macros, determine_macro_dominant


def get_bi_dashboard_data(db: Session, exclusions: list[str]):
    # Time window: Last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    receipts = (
        db.query(Receipt)
        .filter(Receipt.purchase_date >= thirty_days_ago, Receipt.status == "completed")
        .all()
    )

    total_spend = 0.0
    macro_spend = {
        "Protein-dominant": 0.0,
        "Carb-dominant": 0.0,
        "Fat-dominant": 0.0,
        "Mixed macro": 0.0,
        "Non-nutritive / Other": 0.0,
        "Missing USDA Data": 0.0,
    }

    protein_sources = []
    category_metrics = {}

    for r in receipts:
        total_spend += r.total_amount
        for ri in r.items:
            # Skip exclusions
            cat_name = ri.item.category.name if ri.item and ri.item.category else "Uncategorized"
            if any(ex in cat_name.lower() for ex in exclusions):
                continue

            item_spend = ri.price

            if cat_name not in category_metrics:
                category_metrics[cat_name] = {"spend": 0, "protein_g": 0, "carbs_g": 0, "kcal": 0}
            category_metrics[cat_name]["spend"] += item_spend

            # Check macros
            macros = calculate_receipt_item_macros(ri)
            if macros:
                dominant = determine_macro_dominant(macros)
                macro_spend[dominant] += item_spend

                category_metrics[cat_name]["protein_g"] += macros.get("protein_g", 0)
                category_metrics[cat_name]["carbs_g"] += macros.get("carbs_g", 0)
                category_metrics[cat_name]["kcal"] += macros.get("energy_kcal", 0)

                # Protein ROI
                if macros.get("protein_g", 0) > 5 and item_spend > 0:
                    cpp = item_spend / macros["protein_g"]
                    protein_sources.append(
                        {
                            "name": f"{ri.item.name} ({r.store.name if r.store else 'Unknown'})",
                            "cpp": cpp,
                        }
                    )
            else:
                macro_spend["Missing USDA Data"] += item_spend

    # Format Macro Breakdown
    bi_macro = []
    colors = {
        "Protein-dominant": "#10b981",
        "Carb-dominant": "#f59e0b",
        "Fat-dominant": "#3b82f6",
        "Mixed macro": "#8b5cf6",
        "Non-nutritive / Other": "#6b7280",
        "Missing USDA Data": "#ef4444",
    }

    examples = {
        "Protein-dominant": "Eggs, Greek Yogurt, Chicken",
        "Carb-dominant": "Bread, Rice, Pasta, Fruit",
        "Fat-dominant": "Cheese, Nuts, Olive Oil",
        "Mixed macro": "Avocado, Whole Milk, Salmon",
        "Non-nutritive / Other": "Coffee, Spices, Paper Goods",
        "Missing USDA Data": "Items without FDC data matched",
    }

    valid_spend = sum(macro_spend.values())
    if valid_spend > 0:
        for k, v in macro_spend.items():
            if v > 0:
                bi_macro.append(
                    {
                        "label": k,
                        "color": colors.get(k, "#6b7280"),
                        "pct": round((v / valid_spend) * 100),
                        "spend": round(v, 2),
                        "examples": examples.get(k, ""),
                    }
                )

    # Sort ROI best first
    protein_sources.sort(key=lambda x: x["cpp"])
    # Deduplicate by item name to show variety
    seen_roi = set()
    unique_roi = []
    for p in protein_sources:
        if p["name"] not in seen_roi:
            seen_roi.add(p["name"])
            unique_roi.append(p)

    bi_roi = unique_roi[:10]

    # Efficiency Matrix
    bi_cats = []
    for k, v in category_metrics.items():
        if v["spend"] > 0:
            cpp = v["spend"] / v["protein_g"] if v["protein_g"] > 0 else None
            cpc = v["spend"] / v["carbs_g"] if v["carbs_g"] > 0 else None
            cpcal = v["spend"] / v["kcal"] if v["kcal"] > 0 else None

            bi_cats.append(
                {"name": k, "cpp": cpp, "cpc": cpc, "cpcal": cpcal, "spend": round(v["spend"], 2)}
            )

    bi_cats.sort(key=lambda x: x["spend"], reverse=True)

    return {
        "kpis": {
            "monthly_spend": round(total_spend, 2),
            "avg_daily_spend": round(total_spend / 30, 2),
        },
        "macro_breakdown": sorted(bi_macro, key=lambda x: x["pct"], reverse=True),
        "protein_roi": bi_roi,
        "efficiency": bi_cats[:8],
    }
