"""Tests for the Event Bus."""
import pytest
from fastapi.testclient import TestClient

from app.plugins import Event, get_event_bus, reset_event_bus


@pytest.fixture(autouse=True)
def fresh_bus():
    """Ensure a fresh event bus for each test."""
    reset_event_bus()
    yield
    reset_event_bus()


def test_emit_and_subscribe():
    bus = get_event_bus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe("test.event", handler)
    bus.emit("test.event", {"value": 42})

    assert len(received) == 1
    assert received[0].name == "test.event"
    assert received[0].payload == {"value": 42}


def test_multiple_subscribers():
    bus = get_event_bus()
    calls: list[str] = []

    def h1(event: Event):
        calls.append("h1")

    def h2(event: Event):
        calls.append("h2")

    bus.subscribe("multi", h1)
    bus.subscribe("multi", h2)
    bus.emit("multi", {})

    assert calls == ["h1", "h2"]


def test_unsubscribe():
    bus = get_event_bus()
    calls = 0

    def handler(event: Event):
        nonlocal calls
        calls += 1

    bus.subscribe("unsub", handler)
    bus.emit("unsub", {})
    assert calls == 1

    bus.unsubscribe("unsub", handler)
    bus.emit("unsub", {})
    assert calls == 1


def test_emit_no_subscribers():
    bus = get_event_bus()
    # Should not raise
    count = bus.emit("nonexistent", {"x": 1})
    assert count == 0


def test_event_dataclass():
    e = Event(name="test", payload={"a": 1})
    assert e.name == "test"
    assert e.payload == {"a": 1}


def test_emit_async_returns_immediately():
    import time
    bus = get_event_bus()
    start = time.time()
    bus.emit_async("async", {})
    elapsed = time.time() - start
    # emit_async should return immediately (< 0.1s)
    assert elapsed < 0.1


def test_transaction_created_emits_event(client: TestClient):
    bus = get_event_bus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe("transaction.created", handler)
    account_id = client.post(
        "/api/accounts", json={"name": "Test", "initial_balance_cents": 0}
    ).json()["id"]
    response = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
    })
    assert response.status_code == 201
    assert len(received) == 1
    assert received[0].payload == {
        "id": response.json()["id"],
        "account_id": account_id,
        "type": "INCOME",
        "amount_cents": 10000,
        "reversal": False,
    }


def test_transaction_reversal_emits_event(client: TestClient):
    account_id = client.post(
        "/api/accounts", json={"name": "Test", "initial_balance_cents": 0}
    ).json()["id"]
    tx_id = client.post("/api/transactions", json={
        "account_id": account_id,
        "type": "EXPENSE",
        "amount_cents": 10000,
    }).json()["id"]

    bus = get_event_bus()
    received: list[Event] = []

    def handler(event: Event):
        received.append(event)

    bus.subscribe("transaction.created", handler)
    response = client.post(f"/api/transactions/{tx_id}/reverse")
    assert response.status_code == 201
    assert len(received) == 1
    assert received[0].payload["id"] == response.json()["id"]
    assert received[0].payload["reversal"] is True