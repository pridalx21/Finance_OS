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


def test_idempotency_compares_the_date(client: TestClient):
    """The date is part of the payload - a different date is a conflict."""
    account_id = _create_account(client)
    key = "date-key"
    first = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "date": "2026-05-01T00:00:00",
        "idempotency_key": key,
    })
    assert first.status_code == 201

    # Same payload -> same result
    same = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "date": "2026-05-01T00:00:00",
        "idempotency_key": key,
    })
    assert same.status_code == 201
    assert same.json()["id"] == first.json()["id"]

    # Different date -> conflict
    different = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "date": "2026-05-02T00:00:00",
        "idempotency_key": key,
    })
    assert different.status_code == 409


def test_idempotency_without_a_date_is_stable(client: TestClient):
    """A date assigned by the server must not turn a retry into a conflict."""
    account_id = _create_account(client)
    key = "no-date-key"
    payload = {
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "idempotency_key": key,
    }
    first = client.post("/api/transactions", json=payload)
    second = client.post("/api/transactions", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    total = client.get(f"/api/transactions?account_id={account_id}").json()
    assert total["total"] == 1


def test_idempotency_compares_the_description(client: TestClient):
    account_id = _create_account(client)
    key = "description-key"
    client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "description": "Lohn",
        "idempotency_key": key,
    })
    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "description": "Bonus",
        "idempotency_key": key,
    })
    assert response.status_code == 409


def test_reverse_keeps_the_original_in_the_history(client: TestClient):
    account_id = _create_account(client)
    tx_id = client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 30000,
    }).json()["id"]

    reversal = client.post(f"/api/transactions/{tx_id}/reverse")
    assert reversal.status_code == 201
    reversal_id = reversal.json()["id"]

    # The original is still there and marked as voided
    original = client.get(f"/api/transactions/{tx_id}").json()
    assert original["reversed_by"] == reversal_id

    # The storno points back at the original
    storno = client.get(f"/api/transactions/{reversal_id}").json()
    assert storno["reverses_id"] == tx_id

    # Both rows are visible in the list (history is not removed)
    listed = client.get(f"/api/transactions?account_id={account_id}").json()
    assert listed["total"] == 2


def test_reverse_twice_does_not_create_a_second_storno(client: TestClient, db):
    account_id = _create_account(client)
    tx_id = client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 30000,
    }).json()["id"]

    client.post(f"/api/transactions/{tx_id}/reverse")
    second = client.post(f"/api/transactions/{tx_id}/reverse")
    assert second.status_code == 404

    listed = client.get(f"/api/transactions?account_id={account_id}").json()
    assert listed["total"] == 2


def test_reversed_booking_is_excluded_from_the_monthly_report(client: TestClient):
    account_id = _create_account(client)
    tx_id = client.post("/api/transactions", json={
        "account_id": account_id, "type": "EXPENSE", "amount_cents": 30000,
    }).json()["id"]
    client.post(f"/api/transactions/{tx_id}/reverse")

    trend = client.get(f"/api/reports/monthly-trend?account_id={account_id}").json()
    current = trend[-1]
    assert current["expense_cents"] == 0
    assert current["income_cents"] == 0


def test_backdated_booking_lands_in_its_month(client: TestClient):
    account_id = _create_account(client)
    client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 12345,
        "date": "2026-03-15T00:00:00",
    })
    trend = client.get(f"/api/reports/monthly-trend?account_id={account_id}&months=12").json()
    march = [entry for entry in trend if entry["month"] == "2026-03"]
    assert len(march) == 1
    assert march[0]["expense_cents"] == 12345


def test_balance_with_several_accounts(client: TestClient):
    first = client.post("/api/accounts", json={
        "name": "A", "initial_balance_cents": 100000,
    }).json()["id"]
    second = client.post("/api/accounts", json={
        "name": "B", "initial_balance_cents": 50000,
    }).json()["id"]

    client.post("/api/transactions", json={
        "account_id": first, "type": "EXPENSE", "amount_cents": 20000,
    })
    client.post("/api/transactions", json={
        "account_id": second, "type": "INCOME", "amount_cents": 10000,
    })

    assert client.get(f"/api/accounts/{first}/balance").json()["balance_cents"] == 80000
    assert client.get(f"/api/accounts/{second}/balance").json()["balance_cents"] == 60000


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
