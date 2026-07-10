import datetime
import json
import os
from unittest.mock import patch

import pytest

from app.models import Receipt, Store


@pytest.fixture
def mock_ocr():
    # Patch process_receipt_task in the API module where it's used
    with patch("app.api.receipts.process_receipt_task") as mock:
        yield mock


def test_duplicate_receipt_flow(client, db, mock_ocr):
    """
    Test that uploading two similar receipts triggers a duplicate warning
    on the review page.
    """

    # 1. Setup Mock OCR to simulate background processing
    def side_effect(receipt_id, file_path):
        # We use the 'db' fixture session directly
        receipt = db.query(Receipt).filter(Receipt.id == receipt_id).first()

        mock_data = {
            "store_name": "Test Duplicate Store",
            "purchase_date": datetime.date.today().isoformat(),
            "total_amount": 20.00,
            "items": [],
            "image_filename": os.path.basename(file_path),
        }

        # Mimic store normalization and creation
        from app.services.store_utils import normalize_store_name

        store_name = normalize_store_name(mock_data["store_name"])
        store = db.query(Store).filter(Store.name == store_name).first()
        if not store:
            store = Store(name=store_name)
            db.add(store)
            db.commit()
            db.refresh(store)

        receipt.store_id = store.id
        receipt.total_amount = mock_data["total_amount"]
        receipt.purchase_date = datetime.date.today()
        receipt.ocr_data = json.dumps(mock_data)
        receipt.status = "completed"
        db.commit()

    mock_ocr.side_effect = side_effect

    # 2. Upload Receipt 1
    file_content = b"fake image content"
    files = {"file": ("receipt1.jpg", file_content, "image/jpeg")}

    response = client.post("/api/receipts/upload", files=files)
    assert response.status_code == 200

    import re

    match = re.search(r"/receipts/(\d+)/review", response.text)
    assert match, "Could not find receipt ID in upload response"
    receipt_id_1 = int(match.group(1))
    print(f"Uploaded Receipt 1: ID {receipt_id_1}")

    # 3. Upload Receipt 2 (Duplicate)
    files2 = {"file": ("receipt2.jpg", file_content, "image/jpeg")}
    response = client.post("/api/receipts/upload", files=files2)
    assert response.status_code == 200
    match = re.search(r"/receipts/(\d+)/review", response.text)
    assert match, "Could not find receipt ID in upload response 2"
    receipt_id_2 = int(match.group(1))
    print(f"Uploaded Receipt 2: ID {receipt_id_2}")

    # 4. Check Review Page for Receipt 2
    # It should have the duplicate warning now that both are 'completed'
    response = client.get(f"/receipts/{receipt_id_2}/review")
    assert response.status_code == 200
    html_content = response.text

    # Check for the warning message in the HTML
    assert "Potential Duplicate" in html_content
    assert 'type": "duplicate"' in html_content
    print("Duplicate warning detected in Receipt 2 review page.")

    # 5. Delete Receipt 2
    response = client.delete(f"/api/receipts/{receipt_id_2}")
    assert response.status_code == 200
    print("Receipt 2 deleted successfully.")

    # 6. Verify Receipt 2 is gone
    response = client.get(f"/receipts/{receipt_id_2}/review")
    assert response.status_code == 404
    print("Verified Receipt 2 is 404 Not Found.")

    # 7. Check Receipt 1 is still there
    response = client.get(f"/receipts/{receipt_id_1}/review")
    assert response.status_code == 200
    assert 'type": "duplicate"' not in response.text
    print("Receipt 1 is safe and shows no duplicate warning.")
