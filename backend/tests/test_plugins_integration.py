"""Tests for the investments plugin."""
import pytest
import sys
from decimal import Decimal
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.models.account import Account
from app.plugins import plugin_registry, PluginRegistry
from app.db.database import Base
from app.main import set_plugins_dir_for_testing
from pathlib import Path


TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Point to actual plugins directory
PLUGINS_DIR = Path(__file__).parent.parent / "plugins"
set_plugins_dir_for_testing(PLUGINS_DIR)


def _clear_plugin_modules():
    """Clear plugin modules from sys.modules to force reload."""
    to_delete = [k for k in sys.modules if k.startswith('finance_plugin_')]
    for k in to_delete:
        del sys.modules[k]


# Create a test-specific app with test engine
def create_test_app():
    _clear_plugin_modules()
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
    _clear_plugin_modules()
    
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
    """Get the database session used by the test client."""
    # The session is created in the client fixture but not exposed.
    # We create a new session here for direct database access.
    # Note: This is a separate session from the one used by the test client.
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_investments_plugin_creates_tables(client, db_session):
    """Test that the investments plugin creates its tables."""
    import sys
    import os
    fd = os.open("/tmp/test_debug.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.write(fd, b">>> TEST START <<<\n")
    os.write(fd, b"[TEST] Starting test_investments_plugin_creates_tables\n")
    os.write(fd, b">>> BEFORE ROUTES <<<\n")
    os.close(fd)
    # Print all routes for debugging - check app.routes (all routes including included routers)
    routes = []
    for r in client.app.routes:
        if hasattr(r, 'path'):
            routes.append(r.path)
        elif hasattr(r, 'routes'):
            for sub in r.routes:
                if hasattr(sub, 'path'):
                    routes.append(sub.path)
    print("Registered routes (app.routes):", routes, file=sys.stderr)
    
    # Also check router.routes
    router_routes = []
    for r in client.app.router.routes:
        if hasattr(r, 'path'):
            router_routes.append(r.path)
        elif hasattr(r, 'routes'):
            for sub in r.routes:
                if hasattr(sub, 'path'):
                    router_routes.append(sub.path)
    print("Registered routes (router.routes):", router_routes, file=sys.stderr)
    
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

    # Debug: Check what's in the database directly using the db_session fixture
    from sqlalchemy import select
    investment_table = Base.metadata.tables.get("plugin_investments_investments")
    position_table = Base.metadata.tables.get("plugin_investments_positions")
    if investment_table is not None:
        investments_in_db = db_session.execute(select(investment_table)).fetchall()
        print(f"[TEST DEBUG] Investments in DB: {[(i.id, i.symbol) for i in investments_in_db]}", file=sys.stderr, flush=True)
    if position_table is not None:
        positions_in_db = db_session.execute(select(position_table)).fetchall()
        print(f"[TEST DEBUG] Positions in DB: {[(p.id, p.investment_id, p.quantity) for p in positions_in_db]}", file=sys.stderr, flush=True)
    
    # List positions
    pos_resp = client.get(f"/api/investments/positions?account_id={account_id}")
    import sys
    print(f"Positions response: {pos_resp.status_code} - {pos_resp.text}", file=sys.stderr, flush=True)
    print(f"DEBUG: Response text: {pos_resp.text}", file=sys.stderr, flush=True)
    assert pos_resp.status_code == 200, f"Expected 200, got {pos_resp.status_code}: {pos_resp.text}"
    positions = pos_resp.json()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["quantity"] == "10.00000000"


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