"""Tests for transactions API."""
from fastapi.testclient import TestClient


def _create_account(client: TestClient) -> str:
    resp = client.post("/api/accounts", json={"name": "Test", "initial_balance_cents": 0})
    return resp.json()["id"]


def test_create_income(client: TestClient):
    account_id = _create_account(client)
    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 50000,
        "description": "Gehalt",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "INCOME"
    assert data["amount_cents"] == 50000


def test_create_expense(client: TestClient):
    account_id = _create_account(client)
    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 15000,
        "description": "Einkauf",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "EXPENSE"
    assert data["amount_cents"] == 15000


def test_list_transactions(client: TestClient):
    account_id = _create_account(client)
    client.post("/api/transactions", json={"account_id": account_id, "type": "INCOME", "amount_cents": 10000})
    client.post("/api/transactions", json={"account_id": account_id, "type": "EXPENSE", "amount_cents": 5000})
    response = client.get(f"/api/transactions?account_id={account_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_list_transactions_filter_type(client: TestClient):
    account_id = _create_account(client)
    client.post("/api/transactions", json={"account_id": account_id, "type": "INCOME", "amount_cents": 10000})
    client.post("/api/transactions", json={"account_id": account_id, "type": "EXPENSE", "amount_cents": 5000})
    response = client.get(f"/api/transactions?account_id={account_id}&type=EXPENSE")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["type"] == "EXPENSE"


def test_reverse_transaction(client: TestClient):
    account_id = _create_account(client)
    create_resp = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 5000,
    })
    txn_id = create_resp.json()["id"]

    response = client.post(f"/api/transactions/{txn_id}/reverse")
    assert response.status_code == 201
    data = response.json()
    assert data["type"] == "INCOME"
    assert data["amount_cents"] == 5000


def test_reverse_already_reversed(client: TestClient):
    account_id = _create_account(client)
    create_resp = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 5000,
    })
    txn_id = create_resp.json()["id"]
    client.post(f"/api/transactions/{txn_id}/reverse")

    response = client.post(f"/api/transactions/{txn_id}/reverse")
    assert response.status_code == 404


def test_idempotency(client: TestClient):
    account_id = _create_account(client)
    key = "unique-key-123"
    resp1 = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "idempotency_key": key,
    })
    resp2 = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "idempotency_key": key,
    })
    assert resp1.json()["id"] == resp2.json()["id"]
