"""One-time category taxonomy collapse — funnel every category into the canonical set.

Maps each non-canonical category (USDA/OFF/AI fragments like "Breads & Buns",
"Bananas", "Milk/Milk Substitutes") onto the master taxonomy via
category_mapper.map_category_name, reassigns items, and deletes the emptied
categories. The interceptor in category_mapper prevents re-fragmentation.

Usage:
  uv run python scripts/collapse_categories.py             # dry run: print the plan
  uv run python scripts/collapse_categories.py --apply     # execute (writes a backup first)
  uv run python scripts/collapse_categories.py --restore   # undo from the backup file

Backup: data/category_collapse_backup.json records every item's previous
category assignment plus the deleted category rows.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.append(os.getcwd())

from dotenv import load_dotenv

load_dotenv("../.env", override=True)

from app.database import SessionLocal
from app.models import Category, Item
from app.services.category_mapper import CANONICAL_CATEGORIES, map_category_name

BACKUP_PATH = Path("data/category_collapse_backup.json")


def build_plan(db):
    """Returns (mapping: old Category -> canonical name, item counts)."""
    plan = []
    for cat in db.query(Category).order_by(Category.name).all():
        if cat.name in CANONICAL_CATEGORIES:
            continue
        target = map_category_name(cat.name)
        n_items = db.query(Item).filter(Item.category_id == cat.id).count()
        plan.append((cat, target, n_items))
    return plan


def dry_run(db):
    plan = build_plan(db)
    by_target = defaultdict(list)
    for cat, target, n in plan:
        by_target[target].append((cat.name, n))

    total_cats = total_items = 0
    for target in CANONICAL_CATEGORIES:
        sources = by_target.get(target)
        if not sources:
            continue
        moved = sum(n for _, n in sources)
        total_cats += len(sources)
        total_items += moved
        print(f"\n→ {target}  (+{moved} items from {len(sources)} categories)")
        for name, n in sorted(sources, key=lambda s: -s[1]):
            print(f"    {n:>4}  {name}")
    print(
        f"\nPlan: collapse {total_cats} categories ({total_items} items) into the "
        f"{len(CANONICAL_CATEGORIES)}-category canonical set. Run with --apply to execute."
    )


def apply(db):
    plan = build_plan(db)
    if not plan:
        print("Nothing to collapse — all categories are canonical.")
        return

    # Ensure canonical categories exist
    canonical_ids = {}
    for name in CANONICAL_CATEGORIES:
        cat = db.query(Category).filter(Category.name == name).first()
        if not cat:
            cat = Category(name=name)
            db.add(cat)
            db.flush()
        canonical_ids[name] = cat.id

    backup = {"items": [], "categories": []}
    moved = 0
    for cat, target, _n in plan:
        backup["categories"].append({"id": cat.id, "name": cat.name})
        item_ids = [i.id for i in db.query(Item.id).filter(Item.category_id == cat.id).all()]
        for iid in item_ids:
            backup["items"].append({"item_id": iid, "category_id": cat.id, "category_name": cat.name})
        # Bulk UPDATE + query DELETE, deliberately bypassing the ORM: deleting a
        # Category through the session nulls the FKs of items still in its
        # relationship collection at flush time, silently undoing the reassignment
        if item_ids:
            db.query(Item).filter(Item.id.in_(item_ids)).update(
                {Item.category_id: canonical_ids[target]}, synchronize_session=False
            )
            moved += len(item_ids)
        db.query(Category).filter(Category.id == cat.id).delete(synchronize_session=False)

    BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_PATH.write_text(json.dumps(backup, indent=1))
    db.commit()
    print(
        f"Collapsed {len(plan)} categories; moved {moved} items. "
        f"Backup: {BACKUP_PATH} (restore with --restore)."
    )


def restore(db):
    if not BACKUP_PATH.exists():
        print(f"No backup found at {BACKUP_PATH}")
        return
    backup = json.loads(BACKUP_PATH.read_text())

    # Recreate deleted categories (new ids), then restore item assignments by name
    name_to_id = {}
    for entry in backup["categories"]:
        cat = db.query(Category).filter(Category.name == entry["name"]).first()
        if not cat:
            cat = Category(name=entry["name"])
            db.add(cat)
            db.flush()
        name_to_id[entry["name"]] = cat.id

    restored = 0
    for entry in backup["items"]:
        item = db.query(Item).filter(Item.id == entry["item_id"]).first()
        if item:
            item.category_id = name_to_id[entry["category_name"]]
            restored += 1
    db.commit()
    print(f"Restored {restored} item assignments across {len(name_to_id)} categories.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collapse categories into the canonical taxonomy")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true")
    group.add_argument("--restore", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        if args.apply:
            apply(session)
        elif args.restore:
            restore(session)
        else:
            dry_run(session)
    finally:
        session.close()
