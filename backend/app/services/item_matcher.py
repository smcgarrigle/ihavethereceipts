from typing import Any

from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models import Item, Receipt, ReceiptItem

# Max raw-score gap a same-store item may close via ranking. Affects ordering
# only — never whether an item passes the threshold, and never the reported score.
STORE_CONTEXT_RANK_BOOST = 10


def get_store_item_ids(db: Session, store_id: int) -> set[int]:
    """Ids of all items previously purchased at the given store.

    Query this once per receipt and pass the result to find_similar_items /
    get_best_match, mirroring the existing_items pre-fetch pattern.
    """
    rows = (
        db.query(ReceiptItem.item_id)
        .join(Receipt)
        .filter(Receipt.store_id == store_id)
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def normalize_item_name(name: str) -> str:
    """
    Normalize an item name for comparison:
    - Lowercase
    - Strip whitespace
    """
    if not name:
        return ""
    return name.lower().strip()


def find_similar_items(
    item_name: str,
    db: Session,
    threshold: int = 80,
    limit: int = 5,
    existing_items: list[Item] | None = None,
    store_item_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    """
    Find items similar to the given name using rapidfuzz

    Args:
        item_name: The item name to search for
        db: Database session
        threshold: Minimum similarity score (0-100)
        limit: Maximum number of results
        existing_items: Optional list of pre-fetched items to search within
        store_item_ids: Optional pre-fetched purchase history for the current
            store (see get_store_item_ids); ranks same-store items ahead of
            others within STORE_CONTEXT_RANK_BOOST points of raw similarity

    Returns:
        List of dicts with: {item: Item, score: int}
    """
    normalized_search = normalize_item_name(item_name)

    # Use provided items or fetch all if not provided
    if existing_items is not None:
        all_items = existing_items
    else:
        all_items = db.query(Item).all()

    # Calculate similarity scores
    matches: list[dict[str, Any]] = []
    for item in all_items:
        # Using token_sort_ratio as it handles word reordering well
        # (e.g. "Green Onions" vs "Onions Green")
        score = fuzz.token_sort_ratio(normalized_search, str(item.normalized_name))

        if score >= threshold:
            matches.append({"item": item, "score": score})

    # Sort by score descending. Store context influences ranking only:
    # a same-store item can outrank a slightly better text match, but the
    # threshold check above and the reported scores use raw similarity.
    def rank_key(match: dict[str, Any]) -> float:
        score = float(str(match["score"]))
        if store_item_ids and match["item"].id in store_item_ids:
            score += STORE_CONTEXT_RANK_BOOST
        return score

    matches.sort(key=rank_key, reverse=True)

    return matches[:limit]


def get_best_match(
    item_name: str,
    db: Session,
    threshold: int = 85,
    existing_items: list[Item] | None = None,
    store_item_ids: set[int] | None = None,
) -> Item | None:
    """
    Get the best matching item, or None if no good match
    """
    matches = find_similar_items(
        item_name,
        db,
        threshold=threshold,
        limit=1,
        existing_items=existing_items,
        store_item_ids=store_item_ids,
    )

    if matches:
        return matches[0]["item"] if isinstance(matches[0]["item"], Item) else None

    return None


def find_duplicate_items(db: Session, threshold: int = 85) -> list[dict[str, Any]]:
    """
    Find all potential duplicate items in the database
    """
    all_items = db.query(Item).all()
    duplicates: list[dict[str, Any]] = []

    # Compare each item with every other item
    for i, item1 in enumerate(all_items):
        for item2 in all_items[i + 1 :]:
            score = fuzz.token_sort_ratio(str(item1.normalized_name), str(item2.normalized_name))

            if score >= threshold:
                duplicates.append({"item1": item1, "item2": item2, "score": score})

    # Sort by score descending
    duplicates.sort(key=lambda x: float(str(x["score"])), reverse=True)

    return duplicates


def find_merge_candidates(
    item_name: str,
    item_id: int,
    db: Session,
    existing_items: list[Item] | None = None,
) -> list[dict[str, Any]]:
    """Find existing items that might be duplicates of the given item"""

    # Use provided items or fetch from DB
    if existing_items is not None:
        # Filter out the item itself
        all_items = [i for i in existing_items if i.id != item_id]
    else:
        all_items = db.query(Item).filter(Item.id != item_id).all()

    candidates: list[dict[str, Any]] = []
    normalized_search = normalize_item_name(item_name)

    for existing_item in all_items:
        # Calculate similarity using rapidfuzz token_sort_ratio
        score = fuzz.token_sort_ratio(normalized_search, str(existing_item.normalized_name))

        # If 80%+ similar (score is 0-100)
        if score >= 80:
            candidates.append(
                {
                    "id": existing_item.id,
                    "name": existing_item.name,
                    "similarity": score / 100.0,
                }
            )

    # Sort by similarity (highest first)
    candidates.sort(key=lambda x: float(str(x["similarity"])), reverse=True)

    return candidates
