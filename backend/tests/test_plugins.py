"""Tests for the plugin system."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.plugins import FinancePlugin, PluginRegistry

FIXTURE_DIR = Path(__file__).parent / "fixture_plugins"


def test_discover_finds_plugin_and_ignores_non_plugins():
    registry = PluginRegistry()
    found = registry.discover(FIXTURE_DIR)

    assert found == ["echo"]
    assert [info.name for info in registry.loaded] == ["echo"]
    assert registry.loaded[0].version == "1.2.3"


def test_discover_missing_directory_returns_empty():
    registry = PluginRegistry()
    assert registry.discover(Path(__file__).parent / "does_not_exist") == []
    assert registry.loaded == []


def test_register_rejects_empty_name():
    registry = PluginRegistry()

    class NoName(FinancePlugin):
        name = ""

        def register(self, app):
            pass

    with pytest.raises(ValueError):
        registry.register(NoName())


def test_register_rejects_duplicate_name():
    registry = PluginRegistry()

    class Dup(FinancePlugin):
        name = "dup"

        def register(self, app):
            pass

    registry.register(Dup())
    with pytest.raises(ValueError):
        registry.register(Dup())


def test_discover_rejects_invalid_plugin_object(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("PLUGIN = object()\n", encoding="utf-8")

    registry = PluginRegistry()
    with pytest.raises(TypeError):
        registry.discover(tmp_path)


def test_load_all_registers_routes():
    app = FastAPI()
    registry = PluginRegistry()
    loaded = registry.load_all(app, FIXTURE_DIR)

    assert loaded == ["echo"]
    client = TestClient(app)
    response = client.get("/api/echo")
    assert response.status_code == 200
    assert response.json() == {"echo": True}


def test_load_all_honours_enabled_filter():
    app = FastAPI()
    registry = PluginRegistry()
    loaded = registry.load_all(app, FIXTURE_DIR, enabled={"other"})

    assert loaded == []
    client = TestClient(app)
    assert client.get("/api/echo").status_code == 404


def test_load_all_none_enabled_loads_nothing():
    app = FastAPI()
    registry = PluginRegistry()
    loaded = registry.load_all(app, FIXTURE_DIR, enabled=set())
    assert loaded == []


def test_load_all_is_idempotent_per_app():
    app = FastAPI()
    registry = PluginRegistry()
    assert registry.load_all(app, FIXTURE_DIR) == ["echo"]
    route_count = len(app.routes)

    assert registry.load_all(app, FIXTURE_DIR) == []
    assert len(app.routes) == route_count
    client = TestClient(app)
    assert client.get("/api/echo").status_code == 200


def test_discovery_reuses_loaded_module():
    first = PluginRegistry()
    first.discover(FIXTURE_DIR)
    module = sys.modules["finance_plugin_echo"]

    second = PluginRegistry()
    second.discover(FIXTURE_DIR)
    assert sys.modules["finance_plugin_echo"] is module
    assert second.loaded[0].name == "echo"


def test_plugins_endpoint_lists_loaded_plugins(client):
    response = client.get("/api/plugins")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
