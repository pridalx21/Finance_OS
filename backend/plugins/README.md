# Plugins

Hier liegen optionale Erweiterungen für Finance OS. Der Kern lädt sie beim Start
automatisch (Auto-Discovery). Ein Plugin ergänzt Funktionalität, ohne dass der Kern
geändert werden muss.

## Aufbau

Ein Plugin ist entweder

- eine Datei `mein_plugin.py`, oder
- ein Paket `mein_plugin/__init__.py`

und stellt ein Modul-Attribut `PLUGIN` bereit — eine Instanz von
`app.plugins.base.FinancePlugin`.

```python
# backend/plugins/budget.py
from fastapi import APIRouter
from app.plugins.base import FinancePlugin

router = APIRouter(prefix="/api/budget", tags=["budget"])

@router.get("")
def status():
    return {"ok": True}

class BudgetPlugin(FinancePlugin):
    name = "budget"
    version = "0.1.0"

    def register(self, app):
        app.include_router(router)

PLUGIN = BudgetPlugin()
```

## Aktivieren / Deaktivieren

Alle gefundenen Plugins werden geladen. Über die Umgebungsvariable
`FINANCE_PLUGINS` (kommagetrennt) lässt sich die Menge einschränken:

```
FINANCE_PLUGINS=budget,investments
```

## Regeln

- Jedes Plugin hat eigene Tabellen mit Präfix `plugin_<name>_`.
- Plugins ändern den Kern nicht.
- Geladene Plugins sind unter `GET /api/plugins` sichtbar.
