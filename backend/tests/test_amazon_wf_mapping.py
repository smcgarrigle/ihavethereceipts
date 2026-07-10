from unittest.mock import MagicMock, patch

from app.services.ocr import _extract_json
from app.services.pdf_parser import parse_pdf_receipt


def test_pdf_parser_amazon_wholefoods_mapping():
    # Setup mock page and pdfplumber
    mock_page = MagicMock()
    mock_page.extract_text.return_value = """
    Amazon.com Order Details
    Order placed January 21, 2024
    PICKUP AT Potrero Hill 450 RHODE ISLAND ST SAN FRANCISCO, CA 94107
    Order # 123-4567890-1234567
    Grand Total: $12.34

    Organic Bananas $2.19
    """

    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open") as mock_open:
        mock_open.return_value.__enter__.return_value = mock_pdf

        result = parse_pdf_receipt("fake_path.pdf")

        assert result is not None
        assert result["store_name"] == "Whole Foods Market"
        assert result["order_number"] == "123-4567890-1234567"
        assert result["total_amount"] == 12.34
        assert len(result["items"]) == 1
        assert result["items"][0]["name"] == "Organic Bananas"
        assert result["items"][0]["unit_price"] == 2.19


def test_pdf_parser_amazon_fresh_mapping():
    # Setup mock page and pdfplumber
    mock_page = MagicMock()
    mock_page.extract_text.return_value = """
    Amazon Fresh Order Details
    Order placed January 21, 2024
    Order # 123-4567890-1234567
    Grand Total: $12.34

    Organic Bananas $2.19
    """

    mock_pdf = MagicMock()
    mock_pdf.pages = [mock_page]

    with patch("pdfplumber.open") as mock_open:
        mock_open.return_value.__enter__.return_value = mock_pdf

        result = parse_pdf_receipt("fake_path.pdf")

        assert result is not None
        assert result["store_name"] == "Amazon Fresh"


def test_ocr_json_amazon_wholefoods_override():
    # Test case 1: OCR output with store_name = "Amazon.com" but "Whole Foods" in raw string
    raw_ocr_response_1 = """
    Here is the JSON:
    {
        "store_name": "Amazon.com",
        "purchase_date": "2024-01-21",
        "total_amount": 42.15,
        "items": [
            {"name": "Organic Bananas", "final_price": 2.19, "quantity": 1}
        ]
    }
    Whole Foods Market Potrero Hill logo visible.
    """

    result_1 = _extract_json(raw_ocr_response_1)
    assert result_1["store_name"] == "Whole Foods Market"

    # Test case 2: OCR output with store_name = "Amazon Fresh" but "450 Rhode Island" in raw string
    raw_ocr_response_2 = """
    {
        "store_name": "Amazon Fresh",
        "purchase_date": "2024-02-15",
        "total_amount": 18.50,
        "items": []
    }
    Pickup at 450 Rhode Island St location.
    """

    result_2 = _extract_json(raw_ocr_response_2)
    assert result_2["store_name"] == "Whole Foods Market"

    # Test case 3: OCR output with store_name = "Amazon.com" and no Whole Foods markers
    raw_ocr_response_3 = """
    {
        "store_name": "Amazon.com",
        "purchase_date": "2024-02-15",
        "total_amount": 18.50,
        "items": []
    }
    """

    result_3 = _extract_json(raw_ocr_response_3)
    assert result_3["store_name"] == "Amazon.com"
