"""Tests for the investments plugin and the other real plugins.

The plugin logic is tested against the real plugin directory
(``backend/plugins``) - the code that runs in production.
"""


def test_investments_plugin_creates_tables(plugin_client):
    """Test that the investments plugin creates its tables."""
    # Create account
    account_resp = plugin_client.post("/api/accounts", json={"name": "Test", "currency": "CHF", "initial_balance_cents": 100000})
    account_id = account_resp.json()["id"]

    # Create investment
    inv_resp = plugin_client.post("/api/investments", json={"symbol": "AAPL", "name": "Apple", "type": "stock"})
    assert inv_resp.status_code == 201
    inv_id = inv_resp.json()["id"]

    # Create trade
    trade_resp = plugin_client.post("/api/investments/trades", json={
        "account_id": account_id,
        "investment_id": inv_id,
        "type": "BUY",
        "quantity": "10",
        "price_cents": 15000,
    })
    assert trade_resp.status_code == 201
    assert trade_resp.json()["type"] == "BUY"

    # List positions
    pos_resp = plugin_client.get(f"/api/investments/positions?account_id={account_id}")
    assert pos_resp.status_code == 200, f"Expected 200, got {pos_resp.status_code}: {pos_resp.text}"
    positions = pos_resp.json()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["quantity"] == "10.00000000"


def test_sell_more_than_position_is_atomic(plugin_client, db_session):
    from sqlalchemy import text

    account_id = plugin_client.post("/api/accounts", json={"name": "Test"}).json()["id"]
    inv_id = plugin_client.post("/api/investments", json={
        "symbol": "AAPL", "name": "Apple", "type": "stock",
    }).json()["id"]

    buy_resp = plugin_client.post("/api/investments/trades", json={
        "account_id": account_id,
        "investment_id": inv_id,
        "type": "BUY",
        "quantity": "1",
        "price_cents": 10000,
    })
    assert buy_resp.status_code == 201

    sell_resp = plugin_client.post("/api/investments/trades", json={
        "account_id": account_id,
        "investment_id": inv_id,
        "type": "SELL",
        "quantity": "2",
        "price_cents": 10000,
    })
    assert sell_resp.status_code == 400
    assert sell_resp.json()["detail"] == "Nicht genügend Bestand"

    pos_resp = plugin_client.get(f"/api/investments/positions?account_id={account_id}")
    positions = pos_resp.json()
    assert positions[0]["quantity"] == "1.00000000"

    trade_count = db_session.execute(
        text("select count(*) from plugin_investments_trades")
    ).scalar_one()
    assert trade_count == 1


def test_buy_weighted_average_rounds_half_up(plugin_client):
    account_id = plugin_client.post("/api/accounts", json={"name": "Test"}).json()["id"]
    inv_id = plugin_client.post("/api/investments", json={
        "symbol": "AAPL", "name": "Apple", "type": "stock",
    }).json()["id"]

    for price_cents in (100, 101):
        resp = plugin_client.post("/api/investments/trades", json={
            "account_id": account_id,
            "investment_id": inv_id,
            "type": "BUY",
            "quantity": "1",
            "price_cents": price_cents,
        })
        assert resp.status_code == 201

    pos_resp = plugin_client.get(f"/api/investments/positions?account_id={account_id}")
    positions = pos_resp.json()
    assert positions[0]["quantity"] == "2.00000000"
    assert positions[0]["avg_price_cents"] == 101


def test_investments_plugin_list_investments(plugin_client):
    """Test listing investments."""
    resp = plugin_client.get("/api/investments")
    assert resp.status_code == 200
    # Should be empty initially
    assert isinstance(resp.json(), list)


def test_budget_plugin_creates_tables(plugin_client):
    """Test that the budget plugin creates its tables."""
    account_resp = plugin_client.post("/api/accounts", json={"name": "Test", "currency": "CHF", "initial_balance_cents": 100000})
    account_id = account_resp.json()["id"]

    # Create category
    cat_resp = plugin_client.post("/api/categories", json={"name": "Test", "type": "EXPENSE"})
    cat_id = cat_resp.json()["id"]

    # Create budget
    budget_resp = plugin_client.post("/api/budget", json={
        "account_id": account_id,
        "category_id": cat_id,
        "name": "Test Budget",
        "limit_cents": 50000,
        "period": "monthly",
        "start_date": "2026-01-01T00:00:00",
    })
    assert budget_resp.status_code == 201
    assert budget_resp.json()["name"] == "Test Budget"

    # List budgets
    list_resp = plugin_client.get(f"/api/budget?account_id={account_id}")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_budget_status_excludes_reversed_expense(plugin_client):
    account_id = plugin_client.post(
        "/api/accounts", json={"name": "Test", "initial_balance_cents": 100000}
    ).json()["id"]
    cat_id = plugin_client.post(
        "/api/categories", json={"name": "Test", "type": "EXPENSE"}
    ).json()["id"]
    plugin_client.post("/api/budget", json={
        "account_id": account_id,
        "category_id": cat_id,
        "name": "Test Budget",
        "limit_cents": 50000,
        "period": "monthly",
        "start_date": "2026-01-01T00:00:00",
    })

    tx_id = plugin_client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 10000,
        "category_id": cat_id,
    }).json()["id"]

    before = plugin_client.get(f"/api/budget/status?account_id={account_id}").json()
    assert before[0]["spent_cents"] == 10000

    assert plugin_client.post(f"/api/transactions/{tx_id}/reverse").status_code == 201

    after = plugin_client.get(f"/api/budget/status?account_id={account_id}").json()
    assert after[0]["spent_cents"] == 0
    assert after[0]["remaining_cents"] == 50000


def test_auth_plugin_creates_tables(plugin_client):
    """Test that the auth plugin creates its tables."""
    # Setup first user
    setup_resp = plugin_client.post("/api/auth/setup", json={"username": "test", "pin": "1234"})
    assert setup_resp.status_code == 201
    assert setup_resp.json()["username"] == "test"

    # Login
    login_resp = plugin_client.post("/api/auth/login", json={"username": "test", "pin": "1234"})
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    assert token is not None

    # Get current user
    me_resp = plugin_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "test"


def test_debt_open_partial_full_payment(plugin_client):
    account_id = plugin_client.post("/api/accounts", json={"name": "Test", "initial_balance_cents": 0}).json()["id"]
    debt_id = plugin_client.post("/api/debts", json={
        "account_id": account_id,
        "creditor": "Bank",
        "type": "OWED",
        "amount_cents": 10000,
    }).json()["id"]

    # open
    d = plugin_client.get(f"/api/debts/{debt_id}").json()
    assert d["remaining_cents"] == 10000
    assert d["status"] == "OPEN"

    # partial
    pay = plugin_client.post(f"/api/debts/{debt_id}/payments", json={"amount_cents": 3000})
    assert pay.status_code == 201
    d2 = plugin_client.get(f"/api/debts/{debt_id}").json()
    assert d2["remaining_cents"] == 7000
    assert d2["status"] == "OPEN"

    # full
    plugin_client.post(f"/api/debts/{debt_id}/payments", json={"amount_cents": 7000})
    d3 = plugin_client.get(f"/api/debts/{debt_id}").json()
    assert d3["remaining_cents"] == 0
    assert d3["status"] == "PAID"


def test_debt_payment_does_not_create_transaction(plugin_client):
    account_id = plugin_client.post("/api/accounts", json={"name": "Test", "initial_balance_cents": 0}).json()["id"]
    debt_id = plugin_client.post("/api/debts", json={
        "account_id": account_id,
        "creditor": "Bank",
        "type": "OWED",
        "amount_cents": 5000,
    }).json()["id"]
    plugin_client.post(f"/api/debts/{debt_id}/payments", json={"amount_cents": 2000})
    txs = plugin_client.get(f"/api/transactions?account_id={account_id}").json()
    assert txs["total"] == 0


def test_debt_summary(plugin_client):
    account_id = plugin_client.post("/api/accounts", json={"name": "Test", "initial_balance_cents": 0}).json()["id"]
    plugin_client.post("/api/debts", json={"account_id": account_id, "creditor": "A", "type": "OWED", "amount_cents": 10000})
    plugin_client.post("/api/debts", json={"account_id": account_id, "creditor": "B", "type": "RECEIVABLE", "amount_cents": 4000})
    s = plugin_client.get(f"/api/debts/summary?account_id={account_id}").json()
    assert s["open_debt_cents"] == 10000
    assert s["open_receivable_cents"] == 4000


def test_reconciliation_no_auto_booking(plugin_client):
    account_id = plugin_client.post("/api/accounts", json={"name": "Test", "initial_balance_cents": 100000}).json()["id"]
    # add expense
    plugin_client.post("/api/transactions", json={"account_id": account_id, "type": "EXPENSE", "amount_cents": 10000})
    bal_before = plugin_client.get(f"/api/accounts/{account_id}/balance").json()["balance_cents"]
    tx_count_before = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]

    rec = plugin_client.post("/api/reconciliation", json={
        "account_id": account_id,
        "actual_balance_cents": 80000,
        "note": "test diff",
    })
    assert rec.status_code == 201
    data = rec.json()
    assert data["expected_balance_cents"] == bal_before
    assert data["actual_balance_cents"] == 80000
    assert data["difference_cents"] == 80000 - bal_before

    # no new transaction created
    tx_count_after = plugin_client.get(f"/api/transactions?account_id={account_id}").json()["total"]
    assert tx_count_after == tx_count_before
    # balance unchanged
    bal_after = plugin_client.get(f"/api/accounts/{account_id}/balance").json()["balance_cents"]
    assert bal_after == bal_before

    # list
    lst = plugin_client.get(f"/api/reconciliation?account_id={account_id}").json()
    assert len(lst) == 1
