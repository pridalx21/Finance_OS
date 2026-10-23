"""Finance OS - Main Application."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.db.database import init_db
from app.plugins import plugin_registry
from app.routers import accounts_router, categories_router, transactions_router, reports_router

# Directory scanned for drop-in plugins (backend/plugins)
PLUGINS_DIR = Path(__file__).resolve().parents[1] / "plugins"

# Allow override for testing
_override_plugins_dir: Path | None = None


def set_plugins_dir_for_testing(path: Path | None) -> None:
    """Override the plugins directory (used by tests)."""
    global _override_plugins_dir
    _override_plugins_dir = path


def _get_plugins_dir() -> Path:
    return _override_plugins_dir if _override_plugins_dir is not None else PLUGINS_DIR


def _enabled_plugins() -> set[str] | None:
    """Read the optional FINANCE_PLUGINS allow-list."""
    raw = os.getenv("FINANCE_PLUGINS", "").strip()
    if not raw:
        return None
    return {name.strip() for name in raw.split(",") if name.strip()}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Store engine in app state for plugins
    from app.db.database import engine
    app.state.db_engine = engine
    app.state.loaded_plugins = set()
    plugin_registry.load_all(app, _get_plugins_dir(), enabled=_enabled_plugins())

    # The plugins create their own tables during register(). Run the
    # migrations once more so plugin tables that already existed in an older
    # database get the missing columns.
    from app.db.migrations import run_migrations
    run_migrations(engine)

    # ----- Frontend (built SPA) serving, if a build exists -----
    # Registered AFTER plugins so plugin routes take precedence over the
    # catch-all SPA fallback.
    if not getattr(app.state, "spa_registered", False):
        import os as _os
        _FRONTEND_DIST = _os.path.join(
            _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
            "frontend", "dist",
        )
        if _os.path.isdir(_os.path.join(_FRONTEND_DIST, "assets")):
            app.mount(
                "/assets",
                StaticFiles(directory=_os.path.join(_FRONTEND_DIST, "assets")),
                name="frontend_assets",
            )

            @app.get("/{full_path:path}")
            def _spa_fallback(full_path: str):
                # Let API/docs/health keep their own responses (registered above).
                if full_path.startswith("api/") or full_path in ("docs", "redoc", "openapi.json"):
                    raise HTTPException(status_code=404, detail="Not found")
                index = _os.path.join(_FRONTEND_DIST, "index.html")
                if _os.path.isfile(index):
                    return FileResponse(index)
                raise HTTPException(status_code=404, detail="Frontend not built")

        app.state.spa_registered = True
    yield


app = FastAPI(
    title="Finance OS",
    description="Persönliches Finanzsystem",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (für Frontend-Entwicklung)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(accounts_router)
app.include_router(categories_router)
app.include_router(transactions_router)
app.include_router(reports_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/api/plugins")
def list_plugins():
    """List the plugins loaded in this process."""
    return [
        {"name": info.name, "version": info.version, "module": info.module}
        for info in plugin_registry.loaded
    ]


# (SPA fallback is registered in lifespan, after plugins, so plugin routes
#  take precedence over the catch-all.)
