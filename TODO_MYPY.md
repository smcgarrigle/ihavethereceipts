# TODO: Clear the mypy backlog and return mypy to the commit gate

*Written 2026-07-08. Self-contained handoff — no other context needed. Baseline
measured same day: **242 errors in 40 of 185 files** (`cd backend && uv run mypy .`).*

## Why

The pre-commit mypy hook was removed on 2026-07-08 (commit `ea1d995`) because a
242-error backlog made it unconditionally red, which forced `--no-verify` on every
commit and let real regressions through unchecked. The goal is to clear the backlog
and re-add the hook so the commit gate type-checks again. The gate's other hooks
(pytest fast suite, ruff) are green — **never commit with `--no-verify`**.

~150 of the 242 errors share one root cause (legacy SQLAlchemy model declarations);
~31 are genuine null-safety catches worth fixing on their own merits; the rest is
mechanical annotation tail.

## Ground rules for this repo

- Run everything from `backend/` with `uv`: `cd backend && uv run mypy .`,
  `uv run pytest -q` (the Playwright e2e test is deselected by default via
  `pytest.ini addopts`; don't re-enable it).
- SQLAlchemy installed: **2.0.46** (typed `Mapped`/`mapped_column` fully supported;
  no mypy plugin needed for it). Mypy config: `backend/pyproject.toml [tool.mypy]`
  (already has `plugins = ["pydantic.mypy"]`).
- The live DB is `grocery.db` at the repo root — model changes here must NOT change
  schema. This task is annotation-only: **no Alembic migration should be generated.**
  If `alembic` would autogenerate a diff after your model edits, something is wrong.
- Behavior must not change. After each step: `uv run pytest -q` → 77 passed.

## Step 1 — Ratchet hook first (protects the clean 78% immediately)

Re-add mypy to `.pre-commit-config.yaml` (a comment there marks where it was),
but scoped so it passes today: add a mypy `exclude` (regex) in
`backend/pyproject.toml` covering the dirty-file list below, or use
`[[tool.mypy.overrides]] module = [...] ignore_errors = true` for those modules.
Prefer the overrides form — it's explicit and shrinks file-by-file.

Dirty files at baseline (40):

```
alembic/versions/111bbc2cbd34_add_merge_logs.py
app/api/analytics.py  app/api/analytics_bi_injection.py  app/api/analytics_fragments.py
app/api/bulk.py  app/api/export.py  app/api/items.py  app/api/pages.py
app/api/receipts.py  app/api/receipts_fragments.py  app/api/receipts_review.py
app/api/settings_router.py  app/api/templates.py  app/api/trends.py
app/api/trends_nutrition.py  app/api/xray.py  app/main.py  app/middleware.py
app/models/item.py
app/services/category_cache.py  app/services/external_product.py
app/services/fdc_service.py  app/services/folder_watch.py  app/services/item_matcher.py
app/services/model_manager.py  app/services/ocr.py  app/services/onboarding.py
app/services/pdf_parser.py  app/services/predictions.py
scratch/query_anomalies.py
scripts/_analyze_batch.py  scripts/archive/*.py (3 files)  scripts/backfill_nutrients.py
scripts/backfill_unit_prices.py  scripts/seed_demo.py  scripts/sync_pdfs.py
scripts/test_gemini.py
tests/test_zero_qty_fix.py
```

For `scratch/` and `scripts/archive/` don't bother ratcheting — exclude them
permanently (one-off analysis scripts, not product code).

Commit checkpoint: hook green with exclusions in place.

## Step 2 — Migrate models to SQLAlchemy 2.0 typed style (~150 errors die here)

Files: `backend/app/models/{receipt,item,store,category,merge_log,exclusion,ocr_correction}.py`
plus `backend/app/database.py`.

1. In `database.py`, replace
   `from sqlalchemy.ext.declarative import declarative_base` / `Base = declarative_base()`
   with:
   ```python
   from sqlalchemy.orm import DeclarativeBase

   class Base(DeclarativeBase):
       pass
   ```
2. In each model, convert every column, e.g. in `receipt.py`:
   ```python
   # before
   id = Column(Integer, primary_key=True, index=True)
   image_path = Column(String)
   total_amount = Column(Float)
   # after
   id: Mapped[int] = mapped_column(primary_key=True, index=True)
   image_path: Mapped[str | None] = mapped_column(String)
   total_amount: Mapped[float | None] = mapped_column(Float)
   ```
   **Nullability is the trap**: legacy `Column(...)` without `nullable=False` is
   nullable → annotate `Mapped[T | None]`. Only `nullable=False` / primary keys get
   bare `Mapped[T]`. Check each column against the real schema
   (`sqlite3 grocery.db ".schema receipts"` etc.) — the annotation must match what
   the DB actually holds, or mypy's conclusions will be wrong in dangerous ways.
3. Relationships: `items = relationship(...)` →
   `items: Mapped[list["ReceiptItem"]] = relationship(...)`, back_populates as-is.
4. Run `uv run alembic check` (or `alembic revision --autogenerate` and confirm the
   diff is empty, then delete it) to prove schema equivalence. Run the full pytest.

Commit checkpoint. Then re-run mypy: expect the error count to collapse; remove
now-clean modules from the Step 1 overrides list.

## Step 3 — Fix the ~31 [union-attr] errors (these are real potential bugs)

These are `X | None` used without a None-check. Hotspots at baseline:
- `app/services/pdf_parser.py:106,134,189` (3 errors each)
- `app/api/items.py:586-592` — a `Row | None` from a `.first()` gets `.count` /
  `.first_date` / `.last_date` read off it with no guard → AttributeError on an
  item with no purchase rows. Add an early `if row is None:` branch that returns
  the sensible empty response. **Do not** just assert-not-None to silence it;
  decide what the empty case should actually do, and add a regression test where
  the query legitimately returns nothing.
- `app/services/ocr.py:666,1122,1123`

## Step 4 — Mechanical tail

- 28 × `[var-annotated]`: add annotations like `monthly_totals: dict[str, float] = {}`
  (mypy's own hint names the variable each time).
- Implicit `Optional` defaults (e.g. `app/api/export.py:15` `receipt_id: int = None`)
  → `receipt_id: int | None = None`.
- `[no-any-return]` (15): annotate the function's return type; usually the function
  returns `json.loads(...)` or similar — cast or type the intermediate.
- `[call-overload]` on rapidfuzz (7): these disappear after Step 2 (they're
  `Column[str]` args today). Any that remain: pass `str(...)` explicitly.
- `tests/test_zero_qty_fix.py` and `alembic/versions/111bbc2cbd34_*.py`: small
  one-off fixes; migrations may just need the override list permanently (they're
  frozen history — permanent exclude is acceptable for `alembic/versions/`).

## Step 5 — Remove the ratchet

When `uv run mypy .` is clean with only the permanent excludes
(`scratch/`, `scripts/archive/`, `alembic/versions/`), delete the temporary
overrides from Step 1. Final state: mypy in pre-commit, green, guarding all
product code.

## Definition of done

- `cd backend && uv run mypy .` → 0 errors (permanent excludes only).
- `uv run pytest -q` → 77 passed (plus any new regression tests from Step 3).
- `uv run alembic check` → no schema drift.
- `git commit` passes the full hook chain without `--no-verify`.
- App boots: `uv run uvicorn app.main:app --port 8766` → GET / returns 200.
