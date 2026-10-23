"""Tests for the reconciliation plugin (Phase D).

The central question is the time reference of a reconciliation: the system
balance of a cut-off date must only contain the bookings that were effective
at that date.
"""


def _account(client, initial=0):
    resp = client.post(
        "/api/accounts",
        json={"name": "Test", "currency": "CHF", "initial_balance_cents": initial},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _tx(client, account_id, type_, amount, date):
    resp = client.post(
        "/api/transactions",
        json={
            "account_id": account_id,
            "type": type_,
            "amount_cents": amount,
            "date": date,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ----- expected balance ---------------------------------------------------

def test_expected_balance_for_today(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    _tx(plugin_client, account_id, "INCOME", 20000, "2026-05-01T00:00:00")
    _tx(plugin_client, account_id, "EXPENSE", 5000, "2026-05-02T00:00:00")

    resp = plugin_client.get(
        f"/api/reconciliation/expected-balance?account_id={account_id}"
    )
    assert resp.status_code == 200
    assert resp.json()["expected_balance_cents"] == 115000


def test_expected_balance_for_a_historical_date(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-01-15T00:00:00")
    _tx(plugin_client, account_id, "EXPENSE", 5000, "2026-03-15T00:00:00")

    resp = plugin_client.get(
        "/api/reconciliation/expected-balance"
        f"?account_id={account_id}&date=2026-01-31T00:00:00"
    )
    assert resp.status_code == 200
    assert resp.json()["expected_balance_cents"] == 90000


def test_bookings_after_the_cut_off_do_not_change_the_historical_result(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-01-15T00:00:00")
    _tx(plugin_client, account_id, "EXPENSE", 5000, "2026-03-15T00:00:00")

    before = plugin_client.get(
        "/api/reconciliation/expected-balance"
        f"?account_id={account_id}&date=2026-01-31T00:00:00"
    ).json()
    assert before["expected_balance_cents"] == 90000

    # A booking after the cut-off date
    _tx(plugin_client, account_id, "EXPENSE", 30000, "2026-06-01T00:00:00")

    after = plugin_client.get(
        "/api/reconciliation/expected-balance"
        f"?account_id={account_id}&date=2026-01-31T00:00:00"
    ).json()
    assert after["expected_balance_cents"] == 90000


# ----- reconciliation -----------------------------------------------------

def test_reconciliation_with_current_date(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-01-15T00:00:00")

    resp = plugin_client.post(
        "/api/reconciliation",
        json={"account_id": account_id, "actual_balance_cents": 90000},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["expected_balance_cents"] == 90000
    assert data["difference_cents"] == 0


def test_reconciliation_with_historical_date(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-01-15T00:00:00")
    _tx(plugin_client, account_id, "EXPENSE", 5000, "2026-03-15T00:00:00")

    resp = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 90000,
            "date": "2026-01-31T00:00:00",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    # Only the January booking is effective on 31.01.
    assert data["expected_balance_cents"] == 90000
    assert data["difference_cents"] == 0
    assert data["reconciliation_date"].startswith("2026-01-31")


def test_reversal_after_the_cut_off_does_not_change_the_historical_result(plugin_client):
    """A booking that is voided later still counts at an earlier cut-off date."""
    account_id = _account(plugin_client, initial=100000)
    tx = _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-01-15T00:00:00")

    # The storno is dated now - therefore after the cut-off date.
    assert plugin_client.post(f"/api/transactions/{tx['id']}/reverse").status_code == 201

    resp = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 90000,
            "date": "2026-01-31T00:00:00",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["expected_balance_cents"] == 90000

    # Today the booking is void - the current balance is back to 100000.
    current = plugin_client.get(
        f"/api/reconciliation/expected-balance?account_id={account_id}"
    ).json()
    assert current["expected_balance_cents"] == 100000


def test_reversal_before_the_cut_off_voids_the_booking(plugin_client):
    """A booking that was already voided at the cut-off date does not count."""
    account_id = _account(plugin_client, initial=100000)
    tx = _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-01-15T00:00:00")
    assert plugin_client.post(f"/api/transactions/{tx['id']}/reverse").status_code == 201

    # Cut-off date after the storno (today) -> the booking does not count.
    resp = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 100000,
            "date": "2099-01-01T00:00:00",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["expected_balance_cents"] == 100000


def test_reconciliation_stores_the_difference(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    resp = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 95000,
            "note": "fehlende Buchung",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["expected_balance_cents"] == 100000
    assert data["actual_balance_cents"] == 95000
    assert data["difference_cents"] == -5000
    assert data["note"] == "fehlende Buchung"


def test_reconciliation_is_retrievable(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    created = plugin_client.post(
        "/api/reconciliation",
        json={"account_id": account_id, "actual_balance_cents": 95000},
    ).json()

    fetched = plugin_client.get(f"/api/reconciliation/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["difference_cents"] == -5000

    listed = plugin_client.get(f"/api/reconciliation?account_id={account_id}").json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


def test_reconciliation_does_not_create_a_booking(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    before = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    plugin_client.post(
        "/api/reconciliation",
        json={"account_id": account_id, "actual_balance_cents": 1},
    )
    after = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    assert after["total"] == before["total"] == 0


def test_stored_reconciliation_is_not_changed_by_later_bookings(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    created = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 100000,
            "date": "2026-01-31T00:00:00",
        },
    ).json()
    assert created["expected_balance_cents"] == 100000
    assert created["difference_cents"] == 0

    # Later bookings and a later storno must not overwrite the snapshot
    tx = _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-02-15T00:00:00")
    plugin_client.post(f"/api/transactions/{tx['id']}/reverse")

    fetched = plugin_client.get(f"/api/reconciliation/{created['id']}").json()
    assert fetched["expected_balance_cents"] == 100000
    assert fetched["difference_cents"] == 0
    assert fetched["actual_balance_cents"] == 100000


def test_reconciliation_stores_the_underlying_bookings(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    tx = _tx(plugin_client, account_id, "EXPENSE", 10000, "2026-01-15T00:00:00")

    created = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 90000,
            "date": "2026-01-31T00:00:00",
        },
    ).json()
    assert created["basis_transaction_ids"] == [tx["id"]]


def test_reconciliation_idempotency(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    payload = {
        "account_id": account_id,
        "actual_balance_cents": 90000,
        "idempotency_key": "rec-1",
    }
    first = plugin_client.post("/api/reconciliation", json=payload)
    second = plugin_client.post("/api/reconciliation", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    listed = plugin_client.get(f"/api/reconciliation?account_id={account_id}").json()
    assert len(listed) == 1


def test_reconciliation_idempotency_conflict(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 90000,
            "idempotency_key": "rec-1",
        },
    )
    resp = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 95000,
            "idempotency_key": "rec-1",
        },
    )
    assert resp.status_code == 409


def test_reconciliation_requires_an_actual_balance(plugin_client):
    account_id = _account(plugin_client, initial=100000)
    resp = plugin_client.post("/api/reconciliation", json={"account_id": account_id})
    assert resp.status_code == 422


def test_reconciliation_with_unknown_account_is_404(plugin_client):
    resp = plugin_client.post(
        "/api/reconciliation",
        json={"account_id": "does-not-exist", "actual_balance_cents": 1},
    )
    assert resp.status_code == 404


def test_reconciliation_with_invalid_date_is_rejected(plugin_client):
    account_id = _account(plugin_client, initial=0)
    resp = plugin_client.post(
        "/api/reconciliation",
        json={
            "account_id": account_id,
            "actual_balance_cents": 1,
            "date": "not-a-date",
        },
    )
    assert resp.status_code == 422
