"""Tests for the investments plugin."""
import pytest
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.plugins import plugin_registry, PluginRegistry


TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Point to actual plugins directory
PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


# Create a test-specific app with test engine
def create_test_app():
    test_plugin_registry = PluginRegistry()
    
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
    
    app = FastAPI(title="Finance OS Test", lifespan=lifespan)
    
    # Store test engine in app state BEFORE loading plugins
    app.state.db_engine = test_engine
    
    # Include core routers
    from app.routers import accounts_router, categories_router, transactions_router, reports_router
    app.include_router(accounts_router)
    app.include_router(categories_router)
    app.include_router(transactions_router)
    app.include_router(reports_router)
    
    # Load plugins NOW so models are registered with Base.metadata
    test_plugin_registry.load_all(app, PLUGINS_DIR, enabled=None)
    
    return app


@pytest.fixture(scope="function")
def client():
    # Reset plugin registry
    plugin_registry._plugins.clear()
    plugin_registry._loaded.clear()

    app = create_test_app()
    
    session = TestingSessionLocal()
    try:
        def override_get_db():
            try:
                yield session
            finally:
                pass
        
        app.dependency_overrides[get_db] = override_get_db
        
        # Create ALL tables (core + plugins) NOW that plugins are loaded AND session exists
        Base.metadata.create_all(bind=test_engine)
        
        with TestClient(app) as c:
            yield c
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)
        app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def db_session(client):
    """Separate session for direct database assertions."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_investments_plugin_creates_tables(client):
    """Test that the investments plugin creates its tables."""
    # Create account
    account_resp = client.post("/api/accounts", json={"name": "Test", "currency": "CHF", "initial_balance_cents": 100000})
    account_id = account_resp.json()["id"]

    # Create investment
    inv_resp = client.post("/api/investments", json={"symbol": "AAPL", "name": "Apple", "type": "stock"})
    assert inv_resp.status_code == 201
    inv_id = inv_resp.json()["id"]

    # Create trade
    trade_resp = client.post("/api/investments/trades", json={
        "account_id": account_id,
        "investment_id": inv_id,
        "type": "BUY",
        "quantity": "10",
        "price_cents": 15000,
    })
    assert trade_resp.status_code == 201
    assert trade_resp.json()["type"] == "BUY"

    # List positions
    pos_resp = client.get(f"/api/investments/positions?account_id={account_id}")
    assert pos_resp.status_code == 200, f"Expected 200, got {pos_resp.status_code}: {pos_resp.text}"
    positions = pos_resp.json()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["quantity"] == "10.00000000"


def test_sell_more_than_position_is_atomic(client, db_session):
    account_id = client.post("/api/accounts", json={"name": "Test"}).json()["id"]
    inv_id = client.post("/api/investments", json={
        "symbol": "AAPL", "name": "Apple", "type": "stock",
    }).json()["id"]

    buy_resp = client.post("/api/investments/trades", json={
        "account_id": account_id,
        "investment_id": inv_id,
        "type": "BUY",
        "quantity": "1",
        "price_cents": 10000,
    })
    assert buy_resp.status_code == 201

    sell_resp = client.post("/api/investments/trades", json={
        "account_id": account_id,
        "investment_id": inv_id,
        "type": "SELL",
        "quantity": "2",
        "price_cents": 10000,
    })
    assert sell_resp.status_code == 400
    assert sell_resp.json()["detail"] == "Nicht genügend Bestand"

    pos_resp = client.get(f"/api/investments/positions?account_id={account_id}")
    positions = pos_resp.json()
    assert len(positions) == 1
    assert positions[0]["quantity"] == "1.00000000"

    trade_count = db_session.execute(
        text("select count(*) from plugin_investments_trades")
    ).scalar_one()
    assert trade_count == 1


def test_buy_weighted_average_rounds_half_up(client):
    account_id = client.post("/api/accounts", json={"name": "Test"}).json()["id"]
    inv_id = client.post("/api/investments", json={
        "symbol": "AAPL", "name": "Apple", "type": "stock",
    }).json()["id"]

    for price_cents in (100, 101):
        resp = client.post("/api/investments/trades", json={
            "account_id": account_id,
            "investment_id": inv_id,
            "type": "BUY",
            "quantity": "1",
            "price_cents": price_cents,
        })
        assert resp.status_code == 201

    pos_resp = client.get(f"/api/investments/positions?account_id={account_id}")
    positions = pos_resp.json()
    assert len(positions) == 1
    assert positions[0]["quantity"] == "2.00000000"
    assert positions[0]["avg_price_cents"] == 101


def test_investments_plugin_list_investments(client):
    """Test listing investments."""
    resp = client.get("/api/investments")
    assert resp.status_code == 200
    # Should be empty initially
    assert isinstance(resp.json(), list)


def test_budget_plugin_creates_tables(client):
    """Test that the budget plugin creates its tables."""
    account_resp = client.post("/api/accounts", json={"name": "Test", "currency": "CHF", "initial_balance_cents": 100000})
    account_id = account_resp.json()["id"]

    # Create category
    cat_resp = client.post("/api/categories", json={"name": "Test", "type": "EXPENSE"})
    cat_id = cat_resp.json()["id"]

    # Create budget
    budget_resp = client.post("/api/budget", json={
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
    list_resp = client.get(f"/api/budget?account_id={account_id}")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_budget_status_excludes_reversed_expense(client):
    account_id = client.post(
        "/api/accounts", json={"name": "Test", "initial_balance_cents": 100000}
    ).json()["id"]
    cat_id = client.post(
        "/api/categories", json={"name": "Test", "type": "EXPENSE"}
    ).json()["id"]
    client.post("/api/budget", json={
        "account_id": account_id,
        "category_id": cat_id,
        "name": "Test Budget",
        "limit_cents": 50000,
        "period": "monthly",
        "start_date": "2026-01-01T00:00:00",
    })

    tx_id = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 10000,
        "category_id": cat_id,
    }).json()["id"]

    before = client.get(f"/api/budget/status?account_id={account_id}").json()
    assert before[0]["spent_cents"] == 10000

    assert client.post(f"/api/transactions/{tx_id}/reverse").status_code == 201

    after = client.get(f"/api/budget/status?account_id={account_id}").json()
    assert after[0]["spent_cents"] == 0
    assert after[0]["remaining_cents"] == 50000


def test_auth_plugin_creates_tables(client):
    """Test that the auth plugin creates its tables."""
    # Setup first user
    setup_resp = client.post("/api/auth/setup", json={"username": "test", "pin": "1234"})
    assert setup_resp.status_code == 201
    assert setup_resp.json()["username"] == "test"

    # Login
    login_resp = client.post("/api/auth/login", json={"username": "test", "pin": "1234"})
    assert login_resp.status_code == 200
    token = login_resp.json()["token"]
    assert token is not None

    # Get current user
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["username"] == "test"