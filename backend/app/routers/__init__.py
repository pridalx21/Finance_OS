# backend/app/routers/__init__.py
"""API routers."""
from .accounts import router as accounts_router
from .categories import router as categories_router
from .transactions import router as transactions_router
from .reports import router as reports_router

__all__ = ["accounts_router", "categories_router", "transactions_router", "reports_router"]
