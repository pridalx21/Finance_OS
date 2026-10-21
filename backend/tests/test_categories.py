"""Tests for categories API."""
from fastapi.testclient import TestClient


def test_create_category(client: TestClient):
    response = client.post("/api/categories", json={
        "name": "Lebensmittel",
        "type": "EXPENSE",
        "color": "#ef4444",
        "icon": "shopping-cart",
    })
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Lebensmittel"
    assert data["type"] == "EXPENSE"


def test_list_categories(client: TestClient):
    client.post("/api/categories", json={"name": "Gehalt", "type": "INCOME"})
    client.post("/api/categories", json={"name": "Miete", "type": "EXPENSE"})
    response = client.get("/api/categories")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_categories_filter_type(client: TestClient):
    client.post("/api/categories", json={"name": "Gehalt", "type": "INCOME"})
    client.post("/api/categories", json={"name": "Miete", "type": "EXPENSE"})
    response = client.get("/api/categories?type=EXPENSE")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == "Miete"


def test_seed_categories(client: TestClient):
    response = client.post("/api/categories/seed")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 8  # 2 income + 6 expense


def test_seed_categories_idempotent(client: TestClient):
    client.post("/api/categories/seed")
    response = client.post("/api/categories/seed")
    assert response.status_code == 200
    assert len(response.json()) == 0  # Already seeded
