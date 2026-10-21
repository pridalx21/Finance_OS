"""Simple in-process Event Bus for plugin communication.

Plugins and core modules can emit and subscribe to events without direct
dependencies. Events are delivered synchronously in the same process.

Example:
    bus = get_event_bus()
    bus.subscribe("transaction.created", my_handler)
    bus.emit("transaction.created", {"id": "123", "amount_cents": 1000})
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Any
import threading


@dataclass(frozen=True)
class Event:
    """An event that can be emitted and subscribed to."""
    name: str
    payload: dict[str, Any]


# Global event bus instance
_event_bus: "EventBus | None" = None
_lock = threading.Lock()


class EventBus:
    """In-process pub/sub event bus."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[Event], None]]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Callable[[Event], None]) -> None:
        """Register a handler for an event."""
        self._subscribers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[[Event], None]) -> bool:
        """Remove a handler. Returns True if found and removed."""
        if event_name in self._subscribers:
            try:
                self._subscribers[event_name].remove(handler)
                return True
            except ValueError:
                pass
        return False

    def emit(self, event_name: str, payload: dict[str, Any] | None = None) -> int:
        """Emit an event to all subscribers. Returns number of handlers called."""
        event = Event(name=event_name, payload=payload or {})
        handlers = self._subscribers.get(event_name, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # Log but don't crash other handlers
                import logging
                logging.exception("Event handler failed for %s", event_name)
        return len(handlers)

    def emit_async(self, event_name: str, payload: dict[str, Any] | None = None) -> None:
        """Emit an event in a background thread (fire-and-forget)."""
        import threading
        threading.Thread(target=self.emit, args=(event_name, payload), daemon=True).start()


def get_event_bus() -> EventBus:
    """Return the global event bus instance (singleton)."""
    global _event_bus
    with _lock:
        if _event_bus is None:
            _event_bus = EventBus()
        return _event_bus


def reset_event_bus() -> None:
    """Reset the global event bus (mainly for testing)."""
    global _event_bus
    with _lock:
        _event_bus = None