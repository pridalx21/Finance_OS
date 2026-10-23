"""Tests for the debt management (Phase B).

Covers the invariants of the debt plugin: amounts, remaining amount, status,
idempotency, the link between a payment and a booking, atomicity and the
cancellation of a payment.
"""
import pytest
from sqlalchemy import text


def _account(client, initial=0, name="Test"):
    resp = client.post(
        "/api/accounts",
        json={"name": name, "currency": "CHF", "initial_balance_cents": initial},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _debt(client, **kwargs):
    payload = {"creditor": "Bank", "type": "OWED", "amount_cents": 10000}
    payload.update(kwargs)
    resp = client.post("/api/debts", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


# ----- creating debts ----------------------------------------------------

def test_create_debt_requires_counterparty(plugin_client):
    resp = plugin_client.post("/api/debts", json={"type": "OWED", "amount_cents": 1000})
    assert resp.status_code == 422
    assert "Gläubiger" in resp.json()["detail"]


def test_create_debt_rejects_non_positive_amount(plugin_client):
    resp = plugin_client.post(
        "/api/debts", json={"creditor": "Bank", "type": "OWED", "amount_cents": 0}
    )
    assert resp.status_code == 422


def test_create_debt_rejects_unknown_type(plugin_client):
    resp = plugin_client.post(
        "/api/debts", json={"creditor": "Bank", "type": "SOMETHING", "amount_cents": 100}
    )
    assert resp.status_code == 422
    assert "Typ" in resp.json()["detail"]


def test_create_debt_rejects_unknown_status(plugin_client):
    resp = plugin_client.post(
        "/api/debts",
        json={"creditor": "Bank", "type": "OWED", "amount_cents": 100, "status": "WEIRD"},
    )
    assert resp.status_code == 422


def test_create_receivable(plugin_client):
    debt = _debt(plugin_client, type="RECEIVABLE", amount_cents=5000)
    assert debt["type"] == "RECEIVABLE"
    assert debt["remaining_cents"] == 5000
    assert debt["paid_cents"] == 0
    assert debt["status"] == "OPEN"


def test_create_debt_with_unknown_account_is_rejected(plugin_client):
    resp = plugin_client.post(
        "/api/debts",
        json={
            "creditor": "Bank",
            "type": "OWED",
            "amount_cents": 100,
            "account_id": "does-not-exist",
        },
    )
    assert resp.status_code == 404


def test_create_debt_with_invalid_due_date_is_rejected(plugin_client):
    resp = plugin_client.post(
        "/api/debts",
        json={
            "creditor": "Bank",
            "type": "OWED",
            "amount_cents": 100,
            "due_date": "not-a-date",
        },
    )
    assert resp.status_code == 422


# ----- payments -----------------------------------------------------------

def test_partial_payment_updates_remaining_amount(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments", json={"amount_cents": 3000}
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["amount_cents"] == 3000
    assert data["is_cancelled"] is False

    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 7000
    assert after["paid_cents"] == 3000
    assert after["status"] == "OPEN"
    assert after["payment_count"] == 1


def test_full_payment_sets_status_paid(plugin_client):
    debt = _debt(plugin_client, amount_cents=5000)
    plugin_client.post(f"/api/debts/{debt['id']}/payments", json={"amount_cents": 5000})
    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 0
    assert after["paid_cents"] == 5000
    assert after["status"] == "PAID"


def test_overpayment_is_rejected(plugin_client):
    debt = _debt(plugin_client, amount_cents=5000)
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments", json={"amount_cents": 5001}
    )
    assert resp.status_code == 400
    assert "Restschuld" in resp.json()["detail"]

    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 5000


def test_invalid_payment_amount_is_rejected(plugin_client):
    debt = _debt(plugin_client, amount_cents=5000)
    for payload in ({"amount_cents": 0}, {"amount_cents": -100}, {}):
        resp = plugin_client.post(f"/api/debts/{debt['id']}/payments", json=payload)
        assert resp.status_code == 422, payload


def test_payment_on_unknown_debt_is_404(plugin_client):
    resp = plugin_client.post(
        "/api/debts/does-not-exist/payments", json={"amount_cents": 100}
    )
    assert resp.status_code == 404


def test_payment_on_archived_debt_is_rejected(plugin_client):
    debt = _debt(plugin_client, amount_cents=5000)
    plugin_client.delete(f"/api/debts/{debt['id']}")
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments", json={"amount_cents": 100}
    )
    assert resp.status_code == 409


def test_remaining_amount_equals_amount_minus_payments(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    for amount in (1000, 2500, 500):
        plugin_client.post(f"/api/debts/{debt['id']}/payments", json={"amount_cents": amount})
    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 10000 - 1000 - 2500 - 500
    assert after["paid_cents"] == 4000


# ----- idempotency --------------------------------------------------------

def test_repeated_payment_with_same_key_creates_one_payment(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    payload = {"amount_cents": 2000, "idempotency_key": "pay-1"}

    first = plugin_client.post(f"/api/debts/{debt['id']}/payments", json=payload)
    second = plugin_client.post(f"/api/debts/{debt['id']}/payments", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 8000
    assert after["payment_count"] == 1

    payments = plugin_client.get(f"/api/debts/{debt['id']}/payments").json()
    assert len(payments) == 1


def test_payment_key_reused_with_different_content_is_a_conflict(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 2000, "idempotency_key": "pay-1"},
    )
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 3000, "idempotency_key": "pay-1"},
    )
    assert resp.status_code == 409

    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 8000


def test_debt_idempotency_key_reused_with_different_content_is_a_conflict(plugin_client):
    first = plugin_client.post(
        "/api/debts",
        json={
            "creditor": "Bank",
            "type": "OWED",
            "amount_cents": 1000,
            "idempotency_key": "debt-1",
        },
    )
    assert first.status_code == 201
    same = plugin_client.post(
        "/api/debts",
        json={
            "creditor": "Bank",
            "type": "OWED",
            "amount_cents": 1000,
            "idempotency_key": "debt-1",
        },
    )
    assert same.status_code == 201
    assert same.json()["id"] == first.json()["id"]

    different = plugin_client.post(
        "/api/debts",
        json={
            "creditor": "Bank",
            "type": "OWED",
            "amount_cents": 2000,
            "idempotency_key": "debt-1",
        },
    )
    assert different.status_code == 409


def test_payment_idempotency_key_is_unique_in_the_database(plugin_client, db_session):
    debt = _debt(plugin_client, amount_cents=10000)
    plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 1000, "idempotency_key": "unique-key"},
    )
    # A second row with the same key must be rejected by the database
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO plugin_debts_payments "
                "(id, debt_id, amount_cents, date, created_at, idempotency_key) "
                "VALUES ('dup', :debt, 100, '2026-01-01', '2026-01-01', 'unique-key')"
            ),
            {"debt": debt["id"]},
        )
        db_session.flush()


# ----- payment and booking -----------------------------------------------

def test_payment_can_be_booked_as_expense_on_an_account(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    debt = _debt(plugin_client, account_id=account_id, type="OWED", amount_cents=10000)

    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 4000, "create_transaction": True},
    )
    assert resp.status_code == 201
    payment = resp.json()
    assert payment["transaction_id"] is not None

    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    assert txs["total"] == 1
    assert txs["items"][0]["type"] == "EXPENSE"
    assert txs["items"][0]["amount_cents"] == 4000

    balance = plugin_client.get(f"/api/accounts/{account_id}/balance").json()
    assert balance["balance_cents"] == 100000 - 4000


def test_payment_on_receivable_is_booked_as_income(plugin_client):
    account_id = _account(plugin_client, initial=0)
    debt = _debt(
        plugin_client, account_id=account_id, type="RECEIVABLE", amount_cents=10000
    )
    plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 4000, "create_transaction": True},
    )
    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    assert txs["items"][0]["type"] == "INCOME"

    balance = plugin_client.get(f"/api/accounts/{account_id}/balance").json()
    assert balance["balance_cents"] == 4000


def test_payment_without_booking_has_no_transaction(plugin_client):
    account_id = _account(plugin_client, initial=0)
    debt = _debt(plugin_client, account_id=account_id, amount_cents=10000)
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments", json={"amount_cents": 4000}
    )
    assert resp.status_code == 201
    assert resp.json()["transaction_id"] is None

    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    assert txs["total"] == 0


def test_booking_requires_an_account(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 1000, "create_transaction": True},
    )
    assert resp.status_code == 422


def test_booking_with_unknown_account_is_rejected(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={
            "amount_cents": 1000,
            "create_transaction": True,
            "account_id": "does-not-exist",
        },
    )
    assert resp.status_code == 404

    # The payment must not have been stored
    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 10000
    assert after["payment_count"] == 0


def test_payment_is_not_counted_twice_in_the_balance(plugin_client):
    """The payment reduces the debt, the booking changes the account - once."""
    account_id = _account(plugin_client, initial=100000)
    debt = _debt(plugin_client, account_id=account_id, amount_cents=10000)
    plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 4000, "create_transaction": True},
    )

    balance = plugin_client.get(f"/api/accounts/{account_id}/balance").json()
    assert balance["total_expense_cents"] == 4000
    assert balance["balance_cents"] == 96000

    reports = plugin_client.get(
        f"/api/reports/income-vs-expense?account_id={account_id}"
    ).json()
    assert reports["total_expense_cents"] == 4000


def test_payment_and_booking_are_saved_together(plugin_client, db_session):
    account_id = _account(plugin_client, initial=0)
    debt = _debt(plugin_client, account_id=account_id, amount_cents=10000)
    plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 4000, "create_transaction": True},
    )
    payments = db_session.execute(
        text("SELECT COUNT(*) FROM plugin_debts_payments")
    ).scalar_one()
    transactions = db_session.execute(
        text("SELECT COUNT(*) FROM transactions")
    ).scalar_one()
    assert payments == 1
    assert transactions == 1


def test_booking_is_rolled_back_when_the_payment_fails(plugin_client, db_session):
    """A failed payment must not leave a booking behind."""
    account_id = _account(plugin_client, initial=0)
    debt = _debt(plugin_client, account_id=account_id, amount_cents=10000)
    # Amount exceeds the remaining amount -> rejected before anything is written
    resp = plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 99999, "create_transaction": True},
    )
    assert resp.status_code == 400

    assert db_session.execute(text("SELECT COUNT(*) FROM transactions")).scalar_one() == 0
    assert (
        db_session.execute(text("SELECT COUNT(*) FROM plugin_debts_payments")).scalar_one()
        == 0
    )


# ----- cancelling a payment ----------------------------------------------

def test_cancelling_a_payment_restores_the_remaining_amount(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    payment = plugin_client.post(
        f"/api/debts/{debt['id']}/payments", json={"amount_cents": 3000}
    ).json()

    resp = plugin_client.post(f"/api/debts/payments/{payment['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["is_cancelled"] is True

    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 10000
    assert after["paid_cents"] == 0
    assert after["status"] == "OPEN"

    # The payment stays visible in the history
    payments = plugin_client.get(f"/api/debts/{debt['id']}/payments").json()
    assert len(payments) == 1
    assert payments[0]["is_cancelled"] is True


def test_cancelling_a_booking_voids_the_transaction(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    debt = _debt(plugin_client, account_id=account_id, amount_cents=10000)
    payment = plugin_client.post(
        f"/api/debts/{debt['id']}/payments",
        json={"amount_cents": 4000, "create_transaction": True},
    ).json()

    assert plugin_client.get(f"/api/accounts/{account_id}/balance").json()[
        "balance_cents"
    ] == 96000

    plugin_client.post(f"/api/debts/payments/{payment['id']}/cancel")

    balance = plugin_client.get(f"/api/accounts/{account_id}/balance").json()
    assert balance["balance_cents"] == 100000

    # The booking and its storno are kept in the history
    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    assert txs["total"] == 2


def test_cancelling_a_payment_twice_changes_nothing(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    payment = plugin_client.post(
        f"/api/debts/{debt['id']}/payments", json={"amount_cents": 3000}
    ).json()

    first = plugin_client.post(f"/api/debts/payments/{payment['id']}/cancel")
    second = plugin_client.post(f"/api/debts/payments/{payment['id']}/cancel")
    assert first.status_code == 200
    assert second.status_code == 200

    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 10000


def test_cancelling_an_unknown_payment_is_404(plugin_client):
    resp = plugin_client.post("/api/debts/payments/does-not-exist/cancel")
    assert resp.status_code == 404


# ----- changing a debt ---------------------------------------------------

def test_amount_change_below_the_payments_is_rejected(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    plugin_client.post(f"/api/debts/{debt['id']}/payments", json={"amount_cents": 3000})

    resp = plugin_client.patch(f"/api/debts/{debt['id']}", json={"amount_cents": 2000})
    assert resp.status_code == 400
    assert "Zahlungen" in resp.json()["detail"]

    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["amount_cents"] == 10000
    assert after["remaining_cents"] == 7000


def test_amount_change_keeps_the_payments_and_recalculates(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    plugin_client.post(f"/api/debts/{debt['id']}/payments", json={"amount_cents": 3000})

    resp = plugin_client.patch(f"/api/debts/{debt['id']}", json={"amount_cents": 20000})
    assert resp.status_code == 200
    data = resp.json()
    assert data["amount_cents"] == 20000
    assert data["remaining_cents"] == 17000
    assert data["paid_cents"] == 3000


def test_manual_correction_of_the_remaining_amount(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    resp = plugin_client.patch(f"/api/debts/{debt['id']}", json={"remaining_cents": 8000})
    assert resp.status_code == 200
    data = resp.json()
    assert data["remaining_cents"] == 8000
    assert data["correction_cents"] == -2000

    # A correction above the total amount is rejected
    resp = plugin_client.patch(f"/api/debts/{debt['id']}", json={"remaining_cents": 20000})
    assert resp.status_code == 400


def test_archived_debt_is_not_counted_as_open(plugin_client):
    account_id = _account(plugin_client, initial=0)
    open_debt = _debt(plugin_client, account_id=account_id, amount_cents=10000)
    cancelled = _debt(
        plugin_client, account_id=account_id, creditor="Old", amount_cents=5000
    )
    plugin_client.delete(f"/api/debts/{cancelled['id']}")

    summary = plugin_client.get(f"/api/debts/summary?account_id={account_id}").json()
    assert summary["open_debt_cents"] == 10000
    assert summary["open_count"] == 1
    assert summary["archived_count"] == 1
    assert summary["count"] == 1


def test_summary_separates_debts_and_receivables(plugin_client):
    account_id = _account(plugin_client, initial=0)
    _debt(plugin_client, account_id=account_id, type="OWED", amount_cents=10000)
    _debt(
        plugin_client,
        account_id=account_id,
        type="RECEIVABLE",
        creditor="Mami",
        amount_cents=4000,
    )
    summary = plugin_client.get(f"/api/debts/summary?account_id={account_id}").json()
    assert summary["open_debt_cents"] == 10000
    assert summary["open_receivable_cents"] == 4000
    assert summary["net_open_cents"] == -6000


def test_overdue_does_not_pay_a_debt(plugin_client):
    debt = _debt(
        plugin_client,
        amount_cents=10000,
        due_date="2020-01-01",
    )
    after = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert after["remaining_cents"] == 10000
    assert after["status"] == "OPEN"
    assert after["is_overdue"] is True


def test_payment_can_be_fetched_by_id(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    payment = plugin_client.post(
        f"/api/debts/{debt['id']}/payments", json={"amount_cents": 2500, "note": "Teilzahlung"}
    ).json()

    resp = plugin_client.get(f"/api/debts/payments/{payment['id']}")
    assert resp.status_code == 200
    assert resp.json()["amount_cents"] == 2500
    assert resp.json()["note"] == "Teilzahlung"
    assert resp.json()["is_cancelled"] is False

    missing = plugin_client.get("/api/debts/payments/does-not-exist")
    assert missing.status_code == 404


def test_archived_debt_can_be_reactivated(plugin_client):
    debt = _debt(plugin_client, amount_cents=10000)
    assert plugin_client.delete(f"/api/debts/{debt['id']}").status_code == 200

    archived = plugin_client.get(f"/api/debts/{debt['id']}").json()
    assert archived["status"] == "CANCELLED"
    assert archived["archived_at"] is not None

    resp = plugin_client.patch(f"/api/debts/{debt['id']}", json={"archived": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["archived_at"] is None
    assert data["status"] == "OPEN"
    assert data["remaining_cents"] == 10000


def test_payments_of_an_unknown_debt_are_404(plugin_client):
    resp = plugin_client.get("/api/debts/does-not-exist/payments")
    assert resp.status_code == 404
