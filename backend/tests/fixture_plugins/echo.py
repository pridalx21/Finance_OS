"""Test fixture plugin: exposes a single echo route."""
from fastapi import APIRouter

from app.plugins.base import FinancePlugin

router = APIRouter(prefix="/api/echo", tags=["echo"])


@router.get("")
def echo():
    return {"echo": True}


class EchoPlugin(FinancePlugin):
    name = "echo"
    version = "1.2.3"

    def register(self, app):
        app.include_router(router)


PLUGIN = EchoPlugin()
