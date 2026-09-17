# CM-15 runbook: running the eval on the Mac

Scores Qwen3-VL 8B on a fixed set of 30 image receipts, with and without the
correction memory, so each change can be measured against the same receipts.

## What is being measured

- **Image receipts only.** Measured on the live database, 179 of 205 PDF receipts
  are read by the text parser and never reach the model, and that parser never
  sees the corrections block. Image receipts all reach the model.
- **30 receipts:** Rainbow Grocery 8, Costco 7, Whole Foods Market 6, Safeway 5,
  Kukje Market 4. The list is frozen in `cm15_image_30.txt` and was chosen by
  `select_cm15_set.py`.
- **Reference line** from the extraction already saved in the database (not Qwen):
  recall 88%, precision 100%, name 97.5, price 98%, totals matching 33%.

## Runs

| Run | Code | Corrections | Limit | Answers |
| --- | ---- | ----------- | ----: | ------- |
| A | current | none | — | Qwen with no corrections at all |
| B | before PR #33 (`8e68d2a`) | all stores | 10 | Qwen with the old block |
| C | current | all stores | 10 | Qwen with the cleaned block |
| D | current | this store only | 10 | the cleaned block as a reprocessed receipt sees it |
| E | current | all stores | 25 | whether a larger block helps |
| F | current | all stores | 50 | whether a much larger block helps |

A, B and C are the core comparison. Time run A first: every run covers the same
30 receipts, so its duration is a fair estimate for each of the others.

## Options, explained

- `--live` runs the model again instead of scoring the results already saved.
- `--corrections none` sends no correction block.
- `--corrections global` uses corrections from all stores, as a first upload
  does before its store is known.
- `--corrections store` uses only the receipt's own store, as reprocessing does.
- `--receipt-ids` limits the run to the fixed 30.
- `--json` writes every receipt's scores to a file.
- `CORRECTION_PROMPT_LIMIT` sets how many corrections the block holds.
- `LOCAL_OCR_MAX_HEIGHT` sets the height images are scaled to before the model
  sees them. It is held at 1600 so every run sees the same image.

Every run excludes a receipt's own corrections, so no receipt is scored with its
own answers in the prompt.

---

## 1. On the Linux machine: copy the database

```bash
cd /home/mcgar/projects/grocery-tracker
sqlite3 grocery.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 grocery.db ".backup /tmp/grocery-cm15.db"
sha256sum /tmp/grocery-cm15.db
```

Copy `/tmp/grocery-cm15.db` to the Mac the same way as last time.

The live database uses WAL mode, so a plain file copy can miss recent writes.
The backup command takes a consistent copy. Stopping the app first is what worked
last time and is the safest option.

## 2. On the Mac: put the copy in place

Check the checksum matches the one printed above:

```bash
shasum -a 256 ~/Downloads/grocery-cm15.db
```

Find which file the Mac uses, then set the current one aside rather than
deleting it:

```bash
cd /Users/mcgarrigle/Developer/grocery-tracker
grep DATABASE_URL .env
mv grocery.db grocery.db.before-cm15
cp ~/Downloads/grocery-cm15.db grocery.db
```

Adjust the paths if `DATABASE_URL` points somewhere other than `grocery.db` at
the repository root, or if the copy landed somewhere other than `~/Downloads`.

## 3. Point the image paths at the Mac

Every image path in the database is an absolute path on the Linux machine, so on
the Mac none of the 30 images would be found. This rewrites the paths in the
Mac's copy only:

```bash
sqlite3 grocery.db "UPDATE receipts SET image_path = replace(image_path, '/home/mcgar/projects/grocery-tracker/', '/Users/mcgarrigle/Developer/grocery-tracker/') WHERE image_path LIKE '/home/mcgar/projects/grocery-tracker/%';"
```

## 4. Get the code and check the set

The pull request adding this runbook must be merged first.

```bash
git checkout main
git pull
cd backend
uv sync --extra dev
uv run python scripts/eval_sets/select_cm15_set.py --check
```

It must print `All present, scoreable, and every image is on disk.` If it lists
missing images, copy the uploads across before going further.

## 5. Check nothing in `.env` overrides the run settings

`ocr_eval.py` loads `.env` in a way that overrides the command line. If either
setting below is in `.env`, the value given on the command line is ignored and
the runs silently use the `.env` value instead.

```bash
grep -E "CORRECTION_PROMPT_LIMIT|LOCAL_OCR_MAX_HEIGHT" ../.env
```

This must print nothing. Comment out any line it finds.

`OCR_BACKEND`, `OCR_MODEL` and `OCR_BACKEND_URL` stay as they were set for LM
Studio.

## 6. Prepare

Keep a copy of the list outside the repository, because run B checks out older
code that does not contain it:

```bash
cp scripts/eval_sets/cm15_image_30.txt ~/cm15_ids.txt
mkdir -p ~/cm15
```

Set the existing OCR cache aside:

```bash
mv ../data/ocr_cache ../data/ocr_cache.before-cm15
```

**Why the cache matters.** A cached result is found by the image and the prompt,
not by which model produced it or how the image was scaled. A result saved from
an earlier run, or from a different model, would be reused and scored as Qwen's.
The app creates a fresh empty cache on its own, and every set-aside cache is
kept rather than deleted.

## 7. Runs A, C, D, E and F (current code)

Run from `backend/`. After each run, set its cache aside so the next run starts
empty.

```bash
LOCAL_OCR_MAX_HEIGHT=1600 uv run python scripts/ocr_eval.py --live --corrections none --receipt-ids $(grep -v '^#' ~/cm15_ids.txt) --json ~/cm15/a-none.json
mv ../data/ocr_cache ../data/ocr_cache.cm15-a
```

```bash
LOCAL_OCR_MAX_HEIGHT=1600 CORRECTION_PROMPT_LIMIT=10 uv run python scripts/ocr_eval.py --live --corrections global --receipt-ids $(grep -v '^#' ~/cm15_ids.txt) --json ~/cm15/c-new-global-10.json
mv ../data/ocr_cache ../data/ocr_cache.cm15-c
```

```bash
LOCAL_OCR_MAX_HEIGHT=1600 CORRECTION_PROMPT_LIMIT=10 uv run python scripts/ocr_eval.py --live --corrections store --receipt-ids $(grep -v '^#' ~/cm15_ids.txt) --json ~/cm15/d-new-store-10.json
mv ../data/ocr_cache ../data/ocr_cache.cm15-d
```

```bash
LOCAL_OCR_MAX_HEIGHT=1600 CORRECTION_PROMPT_LIMIT=25 uv run python scripts/ocr_eval.py --live --corrections global --receipt-ids $(grep -v '^#' ~/cm15_ids.txt) --json ~/cm15/e-new-global-25.json
mv ../data/ocr_cache ../data/ocr_cache.cm15-e
```

```bash
LOCAL_OCR_MAX_HEIGHT=1600 CORRECTION_PROMPT_LIMIT=50 uv run python scripts/ocr_eval.py --live --corrections global --receipt-ids $(grep -v '^#' ~/cm15_ids.txt) --json ~/cm15/f-new-global-50.json
mv ../data/ocr_cache ../data/ocr_cache.cm15-f
```

## 8. Run B (code from before PR #33)

The old code fixes the block at 10 corrections, so `CORRECTION_PROMPT_LIMIT` is
not needed.

```bash
cd ..
git checkout 8e68d2a
cd backend
uv sync --extra dev
LOCAL_OCR_MAX_HEIGHT=1600 uv run python scripts/ocr_eval.py --live --corrections global --receipt-ids $(grep -v '^#' ~/cm15_ids.txt) --json ~/cm15/b-old-global-10.json
mv ../data/ocr_cache ../data/ocr_cache.cm15-b
cd ..
git checkout main
cd backend
uv sync --extra dev
```

## 9. Send the results back

Send the six files in `~/cm15/`. The results table and OCR error counts get
built from those and committed with the CM-15 pull request.

## Afterwards

The Mac's own database is still in `grocery.db.before-cm15`. To put it back:

```bash
cd /Users/mcgarrigle/Developer/grocery-tracker
mv grocery.db grocery.db.cm15
mv grocery.db.before-cm15 grocery.db
```
