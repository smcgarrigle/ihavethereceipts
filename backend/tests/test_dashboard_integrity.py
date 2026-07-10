from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.main import app


def test_dashboard_template_integrity(client):
    """
    Verify that the dashboard template contains all the IDs required
     by its JavaScript functions to prevent TypeErrors.
    """
    response = client.get("/")
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, "html.parser")

    # Critical IDs for showStoreHistory()
    assert soup.find(id="store-history-modal") is not None, "Missing store-history-modal ID"
    assert soup.find(id="modal-title") is not None, "Missing modal-title ID"
    assert soup.find(id="storeHistoryChart") is not None, "Missing storeHistoryChart ID"

    # Critical IDs for showCategoryStoreDrilldown()
    assert soup.find(id="category-store-modal") is not None, "Missing category-store-modal ID"
    assert soup.find(id="drilldown-modal-title") is not None, "Missing drilldown-modal-title ID"
    assert soup.find(id="drilldown-modal-content") is not None, "Missing drilldown-modal-content ID"

    # These charts were replaced with Tufte versions and BI dashboards.
    # Asserting that the newer Tufte chart IDs are present instead:
    assert soup.find(id="weeklySpendingChart") is not None, "Missing weeklySpendingChart ID"
    assert soup.find(id="monthlySpendingChart") is not None, "Missing monthlySpendingChart ID"


if __name__ == "__main__":
    # For quick manual verification
    with TestClient(app) as client:
        test_dashboard_template_integrity(client)
        print("Template integrity check passed!")
