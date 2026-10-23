# Finance OS

Persönliches Finanzsystem — modular, erweiterbar, lokal nutzbar.
Backend: FastAPI + SQLite. Frontend: React + TypeScript + Vite.

---

## 1. Funktionsumfang V1

| Bereich | Status | Beschreibung |
|---------|--------|--------------|
| Konten | fertig | Konto mit Währung (CHF) und Anfangssaldo |
| Einnahmen / Ausgaben | fertig | Buchungen mit Kategorie, Datum und Beschreibung |
| Kategorien | fertig | Baum, Archivierung, Standardkategorien |
| Stornierung | fertig | Storno-Buchung, Original bleibt in der Historie |
| Kontostandsberechnung | fertig | `Anfangssaldo + wirksame Einnahmen − wirksame Ausgaben` |
| Kontostandsabgleich | fertig | Stichtag, erwarteter/tatsächlicher Stand, Differenz, Snapshot |
| Schulden / Forderungen | fertig | Typ, Betrag, Restschuld, Zins, Fälligkeit, Status, Zahlungen |
| Rückzahlungen | fertig | Teil-/Vollzahlung, optional als Buchung verknüpft, stornierbar |
| Budgets | fertig | Limit je Konto/Kategorie, Verbrauch aus wirksamen Buchungen |
| Monatsübersichten | fertig | Trend, Einnahme/Ausgabe, Ausgaben nach Kategorie |
| Investments | vorhanden | Wertpapiere, Positionen, Trades (gewichteter Durchschnitt, HALF_UP) |
| Auth | optional | PIN-Login, per `FINANCE_PLUGINS=auth` aktivierbar |

Nicht enthalten (bewusst): Bankanbindung, externe Finanzkonten, KI-Funktionen,
Mehrbenutzerbetrieb, Mandantenfähigkeit.

---

## 2. Architektur

```
Finance_OS/
├── backend/
│   ├── app/                      # Kern
│   │   ├── main.py               # FastAPI-App, lifespan, SPA-Fallback
│   │   ├── db/
│   │   │   ├── database.py       # Engine, Session, init_db
│   │   │   ├── migrations.py     # versionierte, idempotente Migrationen
│   │   │   └── backup.py         # Sicherung / Wiederherstellung (CLI)
│   │   ├── models/               # SQLAlchemy-Modelle (Kern)
│   │   ├── schemas/              # Pydantic-Schemas
│   │   ├── services/             # Geschäftslogik (Konten, Buchungen, Berichte)
│   │   ├── routers/              # HTTP-Routen des Kerns
│   │   └── plugins/              # Plugin-Schnittstelle, Registry, Event-Bus
│   ├── plugins/                  # Drop-in-Plugins (Auto-Discovery)
│   │   ├── debts.py              # Schulden & Forderungen
│   │   ├── reconciliation.py     # Kontostandsabgleich
│   │   ├── budget.py             # Budgets
│   │   ├── investments.py        # Wertpapiere
│   │   └── auth.py               # optionale PIN-Anmeldung
│   └── tests/                    # pytest
├── frontend/                     # React 19, TypeScript, Vite, Tailwind, shadcn/ui
├── data/finance.db               # lokale SQLite-Datenbank (nicht im Git)
├── backups/                      # Sicherungen (nicht im Git)
└── docs/                         # Phasenberichte, ADRs
```

### Berechnungslogik (eine Quelle der Wahrheit)

`backend/app/services/transaction_service.py` definiert, welche Buchungen für
einen Kontostand zählen. Konten, Berichte, Budgets, Schulden und der
Kontostandsabgleich verwenden alle dieselbe Funktion `effective_transactions()`.

```
Kontostand = Anfangssaldo + wirksame Einnahmen − wirksame Ausgaben
```

„Wirksam" heißt: nicht storniert und (bei einem Stichtag) nicht nach dem
Stichtag gebucht. Ein Storno wirkt erst ab dem Zeitpunkt, zu dem es selbst
gebucht wurde.

### Plugin-System

* Auto-Discovery beim Start: Datei `name.py` oder Paket `name/__init__.py`
  mit einem Modul-Attribut `PLUGIN` (Instanz von `FinancePlugin`).
* Dateien und Ordner mit führendem `_` werden ignoriert.
* Feature-Flags über `FINANCE_PLUGINS` (kommagetrennt); ohne Wert alle.
* Geladene Plugins: `GET /api/plugins`.
* Eigene Tabellen mit dem Präfix `plugin_<name>_`.
* Event-Bus (`app.plugins.events`) für die Kommunikation zwischen Modulen.

---

## 3. Installation und Start

Voraussetzungen: Python 3.14+, Node.js 20+.

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

Alternativ (PowerShell im Projektstamm):

```powershell
.\start.ps1
```

API-Dokumentation: <http://127.0.0.1:8001/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

`/api` wird vom Dev-Server auf `127.0.0.1:8001` weitergeleitet.

### Aus dem gebauten Frontend (eine einzige Anwendung)

```bash
cd frontend && npm run build    # erzeugt frontend/dist
cd ../backend && python -m uvicorn app.main:app --port 8001
```

Das Backend liefert dann das gebaute Frontend unter `http://127.0.0.1:8001` aus.

---

## 4. Datenbank und Migrationen

Die Datenbank liegt in `data/finance.db` (SQLite, lokal, ohne externe Dienste).
Der Pfad kann über die Umgebungsvariable `DATABASE_URL` geändert werden.

* `Base.metadata.create_all()` erzeugt nur **fehlende** Tabellen.
* Bestehende Tabellen werden von `backend/app/db/migrations.py` angepasst.
* Jede Migration wird genau einmal ausgeführt und in `schema_migrations`
  protokolliert. Ein fehlgeschlagener Schritt wird beim nächsten Start
  erneut versucht.
* Die Migrationen laufen automatisch beim Start der Anwendung.

Aktuelle Migrationen:

| Version | Name | Inhalt |
|---------|------|--------|
| 1 | `core_and_debt_columns` | Storno-Verweis (`reverses_id`), Idempotenz-Fingerprints, Spalten für Schuldenzahlungen und Abgleich-Snapshots, Rückverweis-Auffüllung |
| 2 | `drop_legacy_debt_tables` | leere Alt-Tabellen der deaktivierten Doppel-Plugins (`plugin_debt_*`, `plugin_schulden_*`) |
| 3 | `performance_indexes` | Indizes für Konto/Datum, Schuld/Konto, Zahlung/Schuld, eindeutiger Idempotenzschlüssel der Zahlungen |
| 4 | `idempotency_fingerprints` | Fingerprint-Spalten für Zahlungen und Abgleiche (Nachmigration für bereits migrierte Datenbanken) |

**Datenverlust ist ausgeschlossen:** Alt-Tabellen werden nur gelöscht, wenn sie
nachweislich leer sind. Ist eine solche Tabelle gefüllt, bleibt sie erhalten
und es erscheint eine Warnung im Log.

### Regeln für Daten und Geldbeträge

* Beträge sind ganzzahlige Rappen (`amount_cents`), niemals `float`.
* Fremdschlüssel werden auf jeder SQLite-Verbindung erzwungen (`PRAGMA foreign_keys=ON`).
* Löschen von Finanzdaten ist nicht vorgesehen; Archivierung über `archived_at`.
* Fremdschlüssel und Eindeutigkeit sind im Modell definiert.

---

## 5. Backup und Wiederherstellung

```bash
cd backend

# Sicherung (Standard: ../backups/finance-<Zeitstempel>.db)
python -m app.db.backup backup

# Sicherung an einen bestimmten Ort
python -m app.db.backup backup -o D:\sicherung\finance.db

# Datei prüfen (Integrität + Pflichttabellen)
python -m app.db.backup verify D:\sicherung\finance.db

# Wiederherstellen (die alte Datenbank bleibt als finance.db.bak erhalten)
python -m app.db.backup restore D:\sicherung\finance.db
```

Die Sicherung nutzt die SQLite-Backup-API und ist damit auch während
laufender Schreibzugriffe konsistent. Beim Wiederherstellen wird die Datei
zuerst geprüft; eine defekte Sicherung wird abgelehnt, ohne die Zieldatei
anzutasten. Der Wiederherstellungstest läuft isoliert gegen eine Kopie
(`backend/tests/test_backup.py`).

---

## 6. Geschäftsregeln

### Buchungen

* Eine Buchung hat genau ein Konto, einen Typ (`INCOME`/`EXPENSE`) und einen
  positiven Betrag.
* Storno: es entsteht eine Gegenbuchung; das Original bleibt sichtbar und
  ist als storniert markiert (`reversed_by`), die Gegenbuchung zeigt auf
  das Original (`reverses_id`).
* Stornierte Buchungen zählen in keinem Kontostand, Bericht und Budget.
* Ein Idempotenzschlüssel schützt vor Doppelbuchungen: derselbe Schlüssel
  mit identischem Inhalt liefert das Original, mit abweichendem Inhalt
  HTTP 409.

### Schulden und Forderungen

* Typ `OWED` = eigene Schuld, `RECEIVABLE` = Forderung.
* Ursprungsbetrag und jede Zahlung sind positiv, der Restbetrag nie negativ.
* Der Restbetrag wird immer neu berechnet:
  `Restbetrag = Ursprungsbetrag − gültige Zahlungen + dokumentierte Korrektur`.
* Eine Zahlung über den Restbetrag hinaus wird abgelehnt (HTTP 400).
* Status: `OPEN`, `PAID` (Restbetrag 0), `CANCELLED` (archiviert/storniert),
  `OVERDUE`. Ein überschrittenes Fälligkeitsdatum macht eine Schuld **nicht**
  zu einer bezahlten Schuld; `is_overdue` ist nur ein Anzeigewert.
* Forderungen und Verbindlichkeiten werden in den Summen getrennt
  ausgewiesen (`open_debt_cents`, `open_receivable_cents`, `net_open_cents`).
* Archivierte bzw. stornierte Schulden zählen nicht als offen.

### Rückzahlungen und Buchungen

* Eine Zahlung kann optional als Buchung verknüpft werden
  (`create_transaction: true`). Die Richtung folgt aus der Art der Schuld:
  eigene Schuld → **Ausgabe**, erhaltene Rückzahlung → **Einnahme**.
* Ohne Verknüpfung bleibt `transaction_id` leer — die Zahlung ist dann
  ausdrücklich „ohne Kontobewegung" erfasst und von einer echten
  Kontozahlung unterscheidbar.
* Zahlung, Buchung und Anpassung des Restbetrags werden in **einer**
  Datenbanktransaktion gespeichert: gelingt ein Teilschritt nicht, wird
  nichts gespeichert.
* Eine Zahlung kann storniert werden. Die Zahlung bleibt in der Historie
  sichtbar (`is_cancelled`), der Restbetrag wird neu berechnet und eine
  verknüpfte Buchung wird storniert.
* Derselbe Idempotenzschlüssel erzeugt nie eine zweite Zahlung; abweichender
  Inhalt führt zu HTTP 409.

### Kontostandsabgleich

* Ein Abgleich speichert Konto, Stichtag, erwarteten Saldo, tatsächlichen
  Saldo, Differenz, Notiz und die zugrunde liegenden Buchungen
  (`basis_transaction_ids`).
* Der erwartete Saldo wird für den Stichtag berechnet: spätere Buchungen
  beeinflussen ihn nicht, eine spätere Stornierung wirkt erst ab ihrem
  eigenen Datum.
* Ein Abgleich erzeugt **keine** Korrekturbuchung und verändert keine
  bestehende Buchung.
* Ein gespeicherter Abgleich ist ein Snapshot: spätere Buchungen überschreiben
  ihn nicht, die Differenz bleibt sichtbar.

---

## 7. Tests

```bash
cd backend
.venv\Scripts\python.exe -m pytest -q          # bzw. source .venv/bin/activate

cd ../frontend
npm run test                                    # Vitest
npm run build                                   # TypeScript-Prüfung + Build
npm run lint                                    # oxlint
```

Die Tests laufen vollständig gegen eine In-Memory-Datenbank; die Datei
`data/finance.db` wird von einem Testlauf **nicht** angefasst.

| Testlauf | Ergebnis |
|----------|----------|
| Backend `pytest -q` | 146 bestanden, 0 fehlgeschlagen |
| Frontend `vitest run` | 29 bestanden, 0 fehlgeschlagen (6 Testdateien) |
| Frontend `npm run build` | erfolgreich (TypeScript + Vite) |
| Frontend `npm run lint` | 1 bekannte, kosmetische Warnung in `ui/button.tsx` |

Testabdeckung der Kernbereiche: `tests/test_debts.py` (Schulden, Rückzahlungen,
Idempotenz, Atomarität), `tests/test_reconciliation.py` (historischer
Kontostand, Storno-Zeitpunkte, Snapshot), `tests/test_transactions.py`
(Storno, Idempotenz, Monatswechsel, rückdatierte Buchungen),
`tests/test_migrations.py` (Migration leerer und bestehender Datenbanken,
Schema-Drift), `tests/test_backup.py` (Sicherung und Wiederherstellung),
`tests/test_plugins_integration.py` (alle echten Plugins).

---

## 8. Bekannte Einschränkungen

* Ein Konto oder eine Kategorie kann doppelt angelegt werden — diese
  Schreibpfade haben keinen Idempotenzschlüssel (Buchungen und Zahlungen
  haben ihn).
* Stornierte Buchungen erscheinen weiterhin in der Transaktionsliste
  (Historie), zählen aber in keiner Summe.
* Ein Storno trägt das Datum der Stornierung, nicht das Datum der
  ursprünglichen Buchung. Deshalb wirkt es auf historische Stichtage erst
  ab dem Storno-Datum.
* Zinseszinsen, Gebühren und Ratenzahlungen werden nicht berechnet; der
  Zinssatz wird nur als Information gespeichert.
* Der Kontostandsabgleich löst keine Differenzen auf — er dokumentiert sie
  nur.
* Im Frontend ist die Bundle-Grösse > 500 kB (Recharts); Code-Splitting ist
  offen.
* Die Investoren-Positionen rechnen mit `Numeric` (Dezimal), nicht mit
  ganzzahligen Rappen — das ist für Stückpreise mit Anteilen nötig.

---

## 9. Version und Migrationshinweise

* `app.__version__` / `GET /api/health`: `0.1.0` (Backend), `1.0.0` (V1-Funktionsumfang).
* Vor dem ersten Start mit dieser Version wird die Datenbank automatisch auf
  Migration 4 gebracht. Es ist **keine** manuelle Aktion nötig.
* Für einen alten Stand (vor den Migrationen) gilt: das Programm startet
  normal, die Migrationen laufen beim Start durch. Die Daten bleiben
  erhalten; vorher empfiehlt sich eine Sicherung:

  ```bash
  cd backend && python -m app.db.backup backup
  ```

* Nach einem Update mit geänderten Tabellen empfiehlt sich zusätzlich eine
  Sicherung, da `create_all` zwar keine Daten löscht, aber keine
  automatische Rückwärtsmigration existiert.
