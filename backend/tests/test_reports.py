"""Tests for reports API."""
from fastapi.testclient import TestClient


def _create_account(client: TestClient) -> str:
    resp = client.post("/api/accounts", json={"name": "Test", "initial_balance_cents": 0})
    return resp.json()["id"]


def test_expenses_by_category(client: TestClient):
    account_id = _create_account(client)

    # Create categories
    cat1 = client.post("/api/categories", json={"name": "Lebensmittel", "type": "EXPENSE"}).json()["id"]
    cat2 = client.post("/api/categories", json={"name": "Transport", "type": "EXPENSE"}).json()["id"]

    # Create expenses
    client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 5000, "category_id": cat1,
    })
    client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 3000, "category_id": cat1,
    })
    client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 2000, "category_id": cat2,
    })

    response = client.get(f"/api/reports/expenses-by-category?account_id={account_id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["category_name"] == "Lebensmittel"
    assert data[0]["total_cents"] == 8000
    assert data[1]["category_name"] == "Transport"
    assert data[1]["total_cents"] == 2000


def test_income_vs_expense(client: TestClient):
    account_id = _create_account(client)
    client.post("/api/transactions", json={"account_id": account_id, "type": "INCOME", "amount_cents": 100000})
    client.post("/api/transactions", json={"account_id": account_id, "type": "EXPENSE", "amount_cents": 30000})

    response = client.get(f"/api/reports/income-vs-expense?account_id={account_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["total_income_cents"] == 100000
    assert data["total_expense_cents"] == 30000
    assert data["net_cents"] == 70000


def test_monthly_trend_shape(client: TestClient):
    account_id = _create_account(client)
    response = client.get(f"/api/reports/monthly-trend?account_id={account_id}&months=6")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 6
    # oldest to newest, each entry has the expected keys
    for entry in data:
        assert set(entry.keys()) == {"month", "income_cents", "expense_cents"}
        assert len(entry["month"]) == 7  # "YYYY-MM"
    assert data == sorted(data, key=lambda e: e["month"])


def test_reports_exclude_reversed_transactions(client: TestClient):
    from datetime import datetime, timezone

    account_id = _create_account(client)
    cat_id = client.post("/api/categories", json={
        "name": "Lebensmittel", "type": "EXPENSE",
    }).json()["id"]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_key = f"{now.year:04d}-{now.month:02d}"

    tx_resp = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 5000,
        "category_id": cat_id,
        "date": now.isoformat(),
    })
    tx_id = tx_resp.json()["id"]
    assert client.post(f"/api/transactions/{tx_id}/reverse").status_code == 201

    by_category = client.get(
        f"/api/reports/expenses-by-category?account_id={account_id}"
    ).json()
    assert by_category == []

    summary = client.get(
        f"/api/reports/income-vs-expense?account_id={account_id}"
    ).json()
    assert summary == {
        "total_income_cents": 0,
        "total_expense_cents": 0,
        "net_cents": 0,
    }

    trend = client.get(
        f"/api/reports/monthly-trend?account_id={account_id}&months=6"
    ).json()
    current = next(entry for entry in trend if entry["month"] == current_key)
    assert current["income_cents"] == 0
    assert current["expense_cents"] == 0


def test_monthly_trend_aggregates_current_month(client: TestClient):
    from datetime import datetime, timezone

    account_id = _create_account(client)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    current_key = f"{now.year:04d}-{now.month:02d}"

    client.post("/api/transactions", json={
        "account_id": account_id, "type": "INCOME", "amount_cents": 40000,
        "date": now.isoformat(),
    })
    client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 12500,
        "date": now.isoformat(),
    })

    response = client.get(f"/api/reports/monthly-trend?account_id={account_id}&months=6")
    data = response.json()
    last = data[-1]
    assert last["month"] == current_key
    assert last["income_cents"] == 40000
    assert last["expense_cents"] == 12500
    # months without transactions are zero-filled
    assert data[0]["income_cents"] == 0
    assert data[0]["expense_cents"] == 0
