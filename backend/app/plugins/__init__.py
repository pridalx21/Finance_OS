"""Plugin system for Finance OS."""
from app.plugins.base import FinancePlugin
from app.plugins.events import Event, EventBus, get_event_bus, reset_event_bus
from app.plugins.registry import PluginInfo, PluginRegistry, plugin_registry

__all__ = [
    "FinancePlugin",
    "PluginInfo",
    "PluginRegistry",
    "plugin_registry",
    "Event",
    "EventBus",
    "get_event_bus",
    "reset_event_bus",
]
