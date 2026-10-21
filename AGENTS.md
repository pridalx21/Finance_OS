# AGENTS.md — verbindliche Arbeitsregeln (Finance OS)

**Projekt:** Finance OS (persönliches Finanzsystem)
**Gültig für:** jede Arbeit an diesem Projekt, ohne Ausnahme
**Stand:** 2026-10-21

## 1. Projektübersicht

Finance OS ist ein modulares, erweiterbares persönliches Finanzsystem.
- **v1.0:** Konto, Einnahmen, Ausgaben nach Kategorien, Dashboard
- **Zukunft:** Aktien, Geschäfte, Budgets, Auth (als Plugins)

## 2. Technologie-Stack

| Schicht | Technologie |
|---------|-------------|
| Backend | Python 3.14, FastAPI 0.157, SQLAlchemy 2.1, Pydantic 2.14 |
| Datenbank | SQLite, im Projektordner (`data/finance.db`) |
| Frontend | React 19, TypeScript 6, Vite 8, Tailwind CSS v4, shadcn/ui (Base UI), Recharts |
| Tests | pytest (Backend), Vitest + Testing Library (Frontend) |
| Ports | Backend `127.0.0.1:8001`, Frontend `localhost:5173` (8000 ist vom Trading Desk belegt) |

## 3. Architektur-Prinzipien

1. **Modular:** Core + Plugins (Auto-Discovery)
2. **Erweiterbar:** Neue Module ohne Core-Änderung
3. **API-First:** Backend bietet REST-API, Frontend ist austauschbar
4. **Offline-fähig:** Lokale Datenbank, keine externe Abhängigkeit
5. **Single Source of Truth:** Ein Konto, ein Datenmodell, ein Schreibpfad

## 4. Geld und Beträge

- **Kein float/Number/REAL für Geld.** Beträge als ganzzahlige kleinste Währungseinheiten (Rappen für CHF).
- **decimal.Decimal** für Kurse, Mengen, Stückpreise.
- **Rundung nur an P1, P2, P3, HALF_UP** (ADR-005).
- **Kein unbekannter Wert als 0.00.** Stattdessen "unbekannt" oder null.

## 5. Buchungen

- Eine Transaktion und alle Bewegungen atomar.
- Ein einziger Schreibpfad (TransactionService).
- Storno statt Löschen.
- Idempotenzschlüssel auf jedem Schreibpfad.
- Geplante Zahlungen sind keine Ausgaben.

## 6. Datenmodell

- Fremdschlüssel und Eindeutigkeit überall.
- Keine Löschung von Finanzdaten (Archivierung über `archived_at`).
- Keine Migration ohne Freigabe.

## 7. Plugin-System

```
backend/
├── app/                 # Kern
│   ├── routers/         # Konto, Kategorien, Transaktionen, Berichte
│   ├── services/        # Geschäftslogik
│   ├── models/          # Datenmodell
│   ├── schemas/         # Pydantic
│   ├── db/              # Datenbank
│   └── plugins/         # Plugin-Interface + Registry
│       ├── base.py      # FinancePlugin
│       └── registry.py  # Discovery + Laden
└── plugins/             # Drop-in-Erweiterungen (investments, business, budgets, auth)
```

- **Auto-Discovery** beim Start (Datei `name.py` oder Paket `name/__init__.py` mit `PLUGIN`)
- **Router-Registrierung** pro Plugin über `register(app)`
- **Feature-Flags** über `FINANCE_PLUGINS` (kommagetrennt); ohne Wert werden alle geladen
- **Sichtbarkeit** geladener Plugins unter `GET /api/plugins`
- **Konvention** Datenbank-Isolation: Tabellen mit Präfix `plugin_<name>_`
- **Geplant:** Event-Bus für Kommunikation zwischen Modulen

Details: `backend/plugins/README.md`.

## 8. Sicherheit

- Keine Telemetrie, keine Drittanbieter.
- Keine ausgehende Verbindung zur Laufzeit.
- Loopback als Vorgabe.
- Keine Geheimnisse im Repository.
- Keine echten Finanzdaten in Tests.

## 9. Abhängigkeiten

- Keine neue Laufzeitabhängigkeit ohne ADR.
- Keine ungenutzte Abhängigkeit.
- Keine zwei Bibliotheken für dieselbe Aufgabe.

## 10. Git

- Keine Commits oder Pushes ohne Freigabe.
- Kein `git reset --hard`, `git clean -fd`, `rm -rf`.
- Bei destruktiven Operationen anhalten und fragen.

## 11. Tests

- Jede neue Funktion muss getestet sein.
- Keine Tests deaktivieren oder löschen.
- Phasenbericht mit Zahlen (Testanzahl, bestanden, fehlgeschlagen).

## 12. Selbstprüfung

Vor jeder Übergabe:
1. Zustand geprüft?
2. Nur freigegebener Umfang?
3. Fachliche Entscheidungen aus Dokumenten?
4. Keine leeren Module?
5. Tests geschrieben?
6. Bestehende Daten geschützt?
7. Bericht mit Zahlen?
