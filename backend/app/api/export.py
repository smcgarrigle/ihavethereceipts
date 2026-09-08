import io
from datetime import datetime

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pandas.api.types import is_object_dtype, is_string_dtype
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Category, Item, Receipt, ReceiptItem, Store

router = APIRouter()

# Characters that make a spreadsheet treat a cell as a formula rather than text.
# Tab and the newlines are here because Excel and LibreOffice strip leading
# whitespace before deciding, so " =1+1" is a formula too.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r", "\n")


def _formula_safe(value):
    """Prefix a text cell that a spreadsheet would otherwise evaluate.

    Item, store and category names come from OCR of a receipt image, so a line
    reading `=cmd|'/c calc'!A1` reaches the export verbatim and runs when the
    file is opened. This is the one finding in the audit that leaves the browser
    entirely: the CSP and the HTML escaping elsewhere have no say in what Excel
    does with a downloaded file.

    Only text is touched. Prices and quantities stay numeric, so a genuinely
    negative number is still a number rather than a quoted string.

    Costs nothing on real data: none of the 1,663 item, store and category names
    in the live database starts with one of these characters.
    """
    if not isinstance(value, str) or not value:
        return value
    if value.startswith(_FORMULA_LEADERS) or value.lstrip().startswith(_FORMULA_LEADERS):
        return "'" + value
    return value


def _safe_frame(data: list[dict]) -> pd.DataFrame:
    """The export frame, with every text cell made inert for spreadsheets.

    Columns are selected by asking whether they hold text, not by comparing
    `dtype == object`: pandas 3 infers a dedicated StringDtype, so that older
    idiom silently matches nothing and the guard does not run at all.
    """
    frame = pd.DataFrame(data)
    for column in frame.columns:
        series = frame[column]
        if is_string_dtype(series) or is_object_dtype(series):
            frame[column] = series.map(_formula_safe)
    return frame


def _get_receipt_data(db: Session, receipt_id: int | None = None):
    """Fetch receipt data as a flat list of dictionaries for pandas"""
    query = (
        db.query(
            Receipt.purchase_date,
            Store.name.label("store"),
            Item.name.label("item"),
            Item.fdc_id.label("fdc_id"),
            Category.name.label("category"),
            ReceiptItem.quantity.label("qty"),
            ReceiptItem.unit_type.label("unit"),
            ReceiptItem.price.label("unit_price"),
            ReceiptItem.weight,
        )
        .join(ReceiptItem, Receipt.id == ReceiptItem.receipt_id)
        .join(Store, Receipt.store_id == Store.id)
        .join(Item, ReceiptItem.item_id == Item.id)
        .outerjoin(Category, Item.category_id == Category.id)
    )

    if receipt_id:
        query = query.filter(Receipt.id == receipt_id)

    results = query.order_by(Receipt.purchase_date.desc()).all()

    data = []
    for r in results:
        # Calculate row total
        total = float(r.unit_price or 0) * float(r.qty or 1)

        data.append(
            {
                "Date": r.purchase_date.strftime("%Y-%m-%d") if r.purchase_date else "N/A",
                "Store": r.store,
                "Item": r.item,
                "Category": r.category or "Other",
                "FDC ID": r.fdc_id or "",
                "Quantity": r.qty,
                "Weight": r.weight,
                "Unit": r.unit or "each",
                "Price": float(r.unit_price or 0),
                "Line Total": round(total, 2),
            }
        )
    return data


@router.get("/receipt/{receipt_id}/csv")
def export_receipt_csv(receipt_id: int, db: Session = Depends(get_db)):
    data = _get_receipt_data(db, receipt_id)
    if not data:
        raise HTTPException(status_code=404, detail="No data found for this receipt")

    df = _safe_frame(data)
    stream = io.StringIO()
    df.to_csv(stream, index=False)

    filename = f"receipt_{receipt_id}_{datetime.now().strftime('%Y%m%d')}.csv"

    return Response(
        content=stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/receipt/{receipt_id}/excel")
def export_receipt_excel(receipt_id: int, db: Session = Depends(get_db)):
    data = _get_receipt_data(db, receipt_id)
    if not data:
        raise HTTPException(status_code=404, detail="No data found for this receipt")

    df = _safe_frame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Receipt Items")

    filename = f"receipt_{receipt_id}_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/all/csv")
def export_all_csv(db: Session = Depends(get_db)):
    data = _get_receipt_data(db)
    if not data:
        raise HTTPException(status_code=404, detail="No purchase history found")

    df = _safe_frame(data)
    stream = io.StringIO()
    df.to_csv(stream, index=False)

    filename = f"grocery_history_{datetime.now().strftime('%Y%m%d')}.csv"

    return Response(
        content=stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/all/excel")
def export_all_excel(db: Session = Depends(get_db)):
    data = _get_receipt_data(db)
    if not data:
        raise HTTPException(status_code=404, detail="No purchase history found")

    df = _safe_frame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Grocery History")

    filename = f"grocery_history_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
