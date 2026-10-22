"""Plugin registry: discovery, registration and loading."""
import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from app.plugins.base import FinancePlugin

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginInfo:
    """Read-only description of a loaded plugin."""

    name: str
    version: str
    module: str


def _load_module_from_path(name: str, path: Path):
    """Import a plugin module from a file path.

    Plugins live outside the application package, so they are loaded by path
    rather than by import name. The module name is prefixed to avoid clashes.
    """
    module_name = f"finance_plugin_{name}"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Plugin '{name}' konnte nicht geladen werden: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class PluginRegistry:
    """Holds discovered plugins and loads the enabled ones into the app."""

    def __init__(self) -> None:
        self._plugins: dict[str, FinancePlugin] = {}
        self._loaded: list[PluginInfo] = []

    @property
    def loaded(self) -> list[PluginInfo]:
        return list(self._loaded)

    def register(self, plugin: FinancePlugin, module: str = "") -> None:
        """Register a plugin instance. Rejects an empty or duplicate name."""
        if not plugin.name:
            raise ValueError("Plugin muss einen Namen haben")
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin '{plugin.name}' ist bereits registriert")
        self._plugins[plugin.name] = plugin
        self._loaded.append(PluginInfo(plugin.name, plugin.version, module))

    def discover(self, directory: Path) -> list[str]:
        """Find plugins in a directory.

        Accepts single-file plugins (`name.py`) and package plugins
        (`name/__init__.py`). Files and directories starting with `_` are
        ignored. A plugin module must expose a module-level ``PLUGIN`` object
        that is a :class:`FinancePlugin` instance.
        """
        directory = Path(directory)
        if not directory.is_dir():
            return []

        found: list[str] = []
        logger.debug("Discovering plugins in %s", directory)
        for entry in sorted(directory.iterdir()):
            if entry.name.startswith("_"):
                continue
            logger.debug("Found plugin file: %s", entry.name)
            if entry.is_file() and entry.suffix == ".py":
                module = _load_module_from_path(entry.stem, entry)
            elif entry.is_dir() and (entry / "__init__.py").is_file():
                module = _load_module_from_path(entry.name, entry / "__init__.py")
            else:
                continue

            plugin = getattr(module, "PLUGIN", None)
            if plugin is None:
                logger.debug("No PLUGIN attribute in %s, skipping", entry.name)
                continue
            if not isinstance(plugin, FinancePlugin):
                raise TypeError(
                    f"PLUGIN in '{entry.name}' muss eine FinancePlugin-Instanz sein"
                )
            if plugin.name in self._plugins:
                continue
            logger.debug("Registering plugin: %s", plugin.name)
            self.register(plugin, module=module.__name__)
            found.append(plugin.name)
        return found

    def load_all(
        self,
        app: FastAPI,
        directory: Path,
        enabled: set[str] | None = None,
    ) -> list[str]:
        """Discover plugins and call ``register`` on the enabled ones.

        ``enabled`` is a set of plugin names. When ``None``, every discovered
        plugin is loaded. Returns the names that were actually loaded.
        """
        logger.debug("load_all called with enabled=%s", enabled)
        self.discover(directory)
        if not hasattr(app.state, "loaded_plugins"):
            app.state.loaded_plugins = set()
        loaded: list[str] = []
        for name, plugin in self._plugins.items():
            logger.debug("Loading plugin: %s", name)
            if enabled is not None and name not in enabled:
                continue
            if name in app.state.loaded_plugins:
                continue
            plugin.register(app)
            app.state.loaded_plugins.add(name)
            loaded.append(name)
        return loaded


# Global registry instance (used by main.py and tests)
plugin_registry = PluginRegistry()
