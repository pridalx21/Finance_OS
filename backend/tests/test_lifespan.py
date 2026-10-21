"""Test that lifespan runs correctly."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[LIFESPAN] Starting up...")
    yield
    print("[LIFESPAN] Shutting down...")

app = FastAPI(title="Test", lifespan=lifespan)

@app.get("/")
def root():
    return {"ok": True}

def test_lifespan():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"ok": True}