"""Test that lifespan runs in integration test context."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Starting up...")
    yield
    print("[LIFESPAN] Shutting down...")

@pytest.fixture
def client():
    app = FastAPI(title="Test", lifespan=lifespan)
    
    @app.get("/")
    def root():
        return {"ok": True}
    
    with TestClient(app) as c:
        yield c

def test_lifespan_in_fixture(client):
    print("[TEST] Making request...")
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"ok": True}