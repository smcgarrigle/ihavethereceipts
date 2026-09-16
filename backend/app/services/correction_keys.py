"""A stable identity for a correction's lesson, independent of its database row.

``ocr_corrections`` rows are deleted and re-created every time a review is saved
again, so a row id is not a durable way to refer to a lesson. The content key
is: the same store, class of receipt, field and from/to values always produce
the same key. Usage records and a person's suppress or pin decisions are keyed
on it, so they survive a re-save.

The Alembic revision that backfills existing rows carries a frozen copy of this
logic, because migrations must not import application code.
``tests/test_correction_keys_and_overrides.py`` keeps the two in agreement.
"""

import hashlib

# ASCII unit separator: joins the parts so "a|b" + "c" can never collide with
# "a" + "b|c", and it does not occur in text typed into the review form.
_SEPARATOR = "\x1f"


def content_key(
    store_id: int | None,
    input_type: str,
    field: str,
    ai_value: str | None,
    approved_value: str | None,
) -> str:
    """40-character hex identity for one lesson.

    Values are trimmed, so a stray space does not make a second lesson; case
    and inner spacing are kept, because those can be the lesson itself.
    """
    parts = [
        "" if store_id is None else str(store_id),
        input_type,
        field,
        (ai_value or "").strip(),
        (approved_value or "").strip(),
    ]
    return hashlib.sha1(_SEPARATOR.join(parts).encode("utf-8"), usedforsecurity=False).hexdigest()
