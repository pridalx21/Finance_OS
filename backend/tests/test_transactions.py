"""Tests for transactions API."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.account import Account
from app.models.transaction import Transaction


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


def test_idempotency_conflict(client: TestClient):
    account_id = _create_account(client)
    key = "conflict-key"
    client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "idempotency_key": key,
    })
    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 5000,
        "idempotency_key": key,
    })
    assert response.status_code == 409


def test_balance_after_reversal(client: TestClient):
    account_id = client.post("/api/accounts", json={
        "name": "Test", "initial_balance_cents": 100000,
    }).json()["id"]
    tx_id = client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 30000,
    }).json()["id"]
    # before reversal
    bal = client.get(f"/api/accounts/{account_id}/balance").json()
    assert bal["balance_cents"] == 70000
    client.post(f"/api/transactions/{tx_id}/reverse")
    bal2 = client.get(f"/api/accounts/{account_id}/balance").json()
    assert bal2["balance_cents"] == 100000


def test_create_transaction_rejects_unknown_account(client: TestClient):
    response = client.post("/api/transactions", json={
        "account_id": "missing",
        "type": "INCOME",
        "amount_cents": 10000,
    })
    assert response.status_code == 404
    assert response.json()["detail"] == "Konto nicht gefunden"


def test_create_transaction_rejects_unknown_category(client: TestClient):
    account_id = _create_account(client)
    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 10000,
        "category_id": "missing",
    })
    assert response.status_code == 404
    assert response.json()["detail"] == "Kategorie nicht gefunden"


def test_create_transaction_rejects_category_type_mismatch(client: TestClient):
    account_id = _create_account(client)
    cat_id = client.post("/api/categories", json={
        "name": "Gehalt",
        "type": "INCOME",
    }).json()["id"]

    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 10000,
        "category_id": cat_id,
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Kategorie-Typ passt nicht zur Buchung"


def test_create_transaction_rejects_archived_category(client: TestClient):
    account_id = _create_account(client)
    cat_id = client.post("/api/categories", json={
        "name": "Alt",
        "type": "EXPENSE",
    }).json()["id"]
    client.patch(f"/api/categories/{cat_id}", json={"archived_at": "2026-01-01T00:00:00"})

    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 10000,
        "category_id": cat_id,
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Kategorie ist archiviert"


def test_db_rejects_transaction_with_unknown_account(db):
    db.add(Transaction(account_id="missing", type="INCOME", amount_cents=10000))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_rejects_deleting_account_with_transactions(db):
    account = Account(name="Test", currency="CHF", initial_balance_cents=0)
    db.add(account)
    db.commit()
    db.refresh(account)
    db.add(Transaction(account_id=account.id, type="INCOME", amount_cents=10000))
    db.commit()

    with pytest.raises(IntegrityError):
        db.execute(text("delete from accounts where id = :id"), {"id": account.id})
        db.commit()
    db.rollback()
