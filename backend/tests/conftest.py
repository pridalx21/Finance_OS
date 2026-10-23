"""Test configuration and fixtures.

The tests run against an in-memory SQLite database. The application engine
is redirected to that database for the whole test session, so a test run can
never touch the database of the user (``data/finance.db``).

Two clients are available:

``client``
    The application with the fixture plugins (``tests/fixture_plugins``).
    Used for the core (accounts, categories, transactions, reports).

``plugin_client``
    The application with the **real** plugins (debts, budget,
    reconciliation, investments, auth). Used for the plugin logic.
"""
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path

import app.db.database as database
from app.db.database import Base, get_db
from app.main import app, set_plugins_dir_for_testing
from app.plugins import PluginRegistry, plugin_registry, plugin_registry as global_plugin_registry

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redirect the application to the test database. `init_db()` (called by the
# application lifespan) uses this engine, so the schema of the real database
# is never created or migrated by a test run.
database.engine = engine

# Point to test fixture plugins (echo, notaplugin)
FIXTURE_PLUGINS_DIR = Path(__file__).parent / "fixture_plugins"
set_plugins_dir_for_testing(FIXTURE_PLUGINS_DIR)

# The real plugins
PLUGINS_DIR = Path(__file__).parent.parent / "plugins"


def create_plugin_app() -> FastAPI:
    """Build an application with the real plugins and the test engine."""
    test_plugin_registry = PluginRegistry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    test_app = FastAPI(title="Finance OS Test", lifespan=lifespan)
    test_app.state.db_engine = engine

    from app.routers import (
        accounts_router,
        categories_router,
        reports_router,
        transactions_router,
    )

    test_app.include_router(accounts_router)
    test_app.include_router(categories_router)
    test_app.include_router(transactions_router)
    test_app.include_router(reports_router)

    # Load the plugins so their models are registered with Base.metadata
    test_plugin_registry.load_all(test_app, PLUGINS_DIR, enabled=None)
    return test_app


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db):
    """Separate session for direct database assertions."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db):
    # Reset plugin registry for each test to avoid duplicate registration
    global_plugin_registry._plugins.clear()
    global_plugin_registry._loaded.clear()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def plugin_client(db):
    """Application with the real plugins (debts, budget, reconciliation, ...)."""
    plugin_registry._plugins.clear()
    plugin_registry._loaded.clear()

    test_app = create_plugin_app()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    test_app.dependency_overrides[get_db] = override_get_db
    with TestClient(test_app) as c:
        yield c
    test_app.dependency_overrides.clear()
