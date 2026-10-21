"""Tests for accounts API."""
from fastapi.testclient import TestClient


def test_create_account(client: TestClient):
    response = client.post("/api/accounts", json={
        "name": "Hauptkonto",
        "currency": "CHF",
        "initial_balance_cents": 100000,
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Hauptkonto"
    assert data["currency"] == "CHF"
    assert data["initial_balance_cents"] == 100000
    assert "id" in data


def test_list_accounts(client: TestClient):
    client.post("/api/accounts", json={"name": "Konto 1"})
    client.post("/api/accounts", json={"name": "Konto 2"})
    response = client.get("/api/accounts")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_account(client: TestClient):
    create_resp = client.post("/api/accounts", json={"name": "Test"})
    account_id = create_resp.json()["id"]
    response = client.get(f"/api/accounts/{account_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Test"


def test_get_account_not_found(client: TestClient):
    response = client.get("/api/accounts/nonexistent")
    assert response.status_code == 404


def test_get_balance(client: TestClient):
    create_resp = client.post("/api/accounts", json={
        "name": "Test",
        "initial_balance_cents": 50000,
    })
    account_id = create_resp.json()["id"]

    # Add income
    client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 30000,
    })
    # Add expense
    client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 10000,
    })

    response = client.get(f"/api/accounts/{account_id}/balance")
    assert response.status_code == 200
    data = response.json()
    assert data["initial_balance_cents"] == 50000
    assert data["total_income_cents"] == 30000
    assert data["total_expense_cents"] == 10000
    assert data["balance_cents"] == 70000
