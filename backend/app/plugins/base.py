"""Plugin base interface."""
from abc import ABC, abstractmethod
from fastapi import FastAPI


class FinancePlugin(ABC):
    """Base class for a Finance OS plugin.

    A plugin bundles optional functionality (routes, models, event handlers)
    that can be added to the application without changing the core.
    """

    #: Unique plugin name, e.g. "investments"
    name: str = ""
    #: Plugin version
    version: str = "0.0.0"

    @abstractmethod
    def register(self, app: FastAPI) -> None:
        """Attach this plugin's routes and startup hooks to the application.

        Called once per process during startup. Must be idempotent per plugin
        instance and must not perform work that belongs in the core.
        """
        raise NotImplementedError
