from rapidfuzz import fuzz
from sqlalchemy.orm import Session

from app.models import Item


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
) -> list[dict]:
    """
    Find items similar to the given name using rapidfuzz

    Args:
        item_name: The item name to search for
        db: Database session
        threshold: Minimum similarity score (0-100)
        limit: Maximum number of results
        existing_items: Optional list of pre-fetched items to search within

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
    matches = []
    for item in all_items:
        # Using token_sort_ratio as it handles word reordering well
        # (e.g. "Green Onions" vs "Onions Green")
        score = fuzz.token_sort_ratio(normalized_search, item.normalized_name)

        if score >= threshold:
            matches.append({"item": item, "score": score})

    # Sort by score descending
    matches.sort(key=lambda x: x["score"], reverse=True)

    return matches[:limit]


def get_best_match(
    item_name: str,
    db: Session,
    threshold: int = 85,
    existing_items: list[Item] | None = None,
) -> Item | None:
    """
    Get the best matching item, or None if no good match
    """
    matches = find_similar_items(
        item_name, db, threshold=threshold, limit=1, existing_items=existing_items
    )

    if matches:
        return matches[0]["item"]

    return None


def find_duplicate_items(db: Session, threshold: int = 85) -> list[dict]:
    """
    Find all potential duplicate items in the database
    """
    all_items = db.query(Item).all()
    duplicates = []

    # Compare each item with every other item
    for i, item1 in enumerate(all_items):
        for item2 in all_items[i + 1 :]:
            score = fuzz.token_sort_ratio(item1.normalized_name, item2.normalized_name)

            if score >= threshold:
                duplicates.append({"item1": item1, "item2": item2, "score": score})

    # Sort by score descending
    duplicates.sort(key=lambda x: x["score"], reverse=True)

    return duplicates


def find_merge_candidates(
    item_name: str,
    item_id: int,
    db: Session,
    existing_items: list[Item] | None = None,
) -> list:
    """Find existing items that might be duplicates of the given item"""

    # Use provided items or fetch from DB
    if existing_items is not None:
        # Filter out the item itself
        all_items = [i for i in existing_items if i.id != item_id]
    else:
        all_items = db.query(Item).filter(Item.id != item_id).all()

    candidates = []
    normalized_search = normalize_item_name(item_name)

    for existing_item in all_items:
        # Calculate similarity using rapidfuzz token_sort_ratio
        score = fuzz.token_sort_ratio(normalized_search, existing_item.normalized_name)

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
    candidates.sort(key=lambda x: x["similarity"], reverse=True)

    return candidates
