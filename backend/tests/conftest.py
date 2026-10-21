"""Test configuration and fixtures."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from pathlib import Path

from app.db.database import Base, get_db
from app.main import app, set_plugins_dir_for_testing
from app.plugins import PluginRegistry, plugin_registry as global_plugin_registry

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Point to test fixture plugins (echo, notaplugin)
FIXTURE_PLUGINS_DIR = Path(__file__).parent / "fixture_plugins"
set_plugins_dir_for_testing(FIXTURE_PLUGINS_DIR)


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
