# Phasenbericht 5 — Hardening (Datenintegrität, Plugin-System, Event-Bus)

## 1. Umfang

Absicherung des Kerns und des Plugin-Systems nach Phase 4. Schwerpunkte:
Datenintegrität (Foreign Keys, Validierung, Storno-Bereinigung in Berichten),
Idempotenz des Plugin-Registries, Event-Bus-Anbindung an Transaktionen,
atomare Investment-Trades, UTC-Zeitstempel, Pydantic-v2-Konfiguration,
Frontend-Dokumentation/Port-Konsistenz und Start-Skript.

## 2. Geänderte Dateien (17)

Backend:
- `backend/app/db/database.py` — `PRAGMA foreign_keys=ON` auf jeder SQLite-Verbindung (Event-Listener auf Engine)
- `backend/app/main.py` — `app.state.loaded_plugins = set()` beim Start
- `backend/app/plugins/registry.py` — Modul-Reuse (`sys.modules`), Duplikat-Skip, `load_all` idempotent pro App, `print` → `logging`
- `backend/app/routers/transactions.py` — `LookupError`→404, `ValueError`→400
- `backend/app/services/transaction_service.py` — Validierung Konto (existiert/nicht archiviert), Kategorie (existiert/nicht archiviert/Typ-Match); `active_transactions()`-Helper; `transaction.created`-Event bei Create und Reversal; `flush()` vor `commit()` bei Reversal
- `backend/app/services/report_service.py` — `active_transactions()` filtert stornierte Originale und Storno-Buchungen aus allen drei Berichten
- `backend/plugins/auth.py` — `_utcnow()`-Helper, `model_config = ConfigDict(from_attributes=True)` statt `Config`
- `backend/plugins/budget.py` — `active_transactions()`, Entfernung der ungenutzten Event-Subscription
- `backend/plugins/investments.py` — `_utcnow()`, `ConfigDict`, atomare Trade-Erstellung (Validierung vor Commit, Rollback bei Fehler), gewichteter Durchschnittspreis gerundet `ROUND_HALF_UP`, Route `GET /{investment_id}` verschoben

Tests:
- `backend/tests/test_events.py` — +2 Tests (`transaction.created` bei Create und Reversal)
- `backend/tests/test_plugins.py` — +2 Tests (Idempotenz `load_all`, Modul-Reuse)
- `backend/tests/test_plugins_integration.py` — +3 Tests (atomarer Sell, HALF_UP-Rundung, Budget exkludiert stornierte Ausgabe), Debug-Code entfernt
- `backend/tests/test_reports.py` — +1 Test (Berichte exkludieren stornierte Transaktionen)
- `backend/tests/test_transactions.py` — +8 Tests (unbekanntes Konto/Kategorie, Typ-Mismatch, archivierte Kategorie, FK-Enforcement, Account-Löschschutz)

Frontend/Doku:
- `frontend/index.html` — `lang="de"`, Titel „Finance OS“
- `frontend/README.md` — aktualisierte Entwickler-Doku
- `start.ps1` — Port 8001, Health-Check, fremden Prozess nicht beenden

## 3. Tests

- Backend: **56 bestanden**, 0 fehlgeschlagen, 1 Warnung (starlette-Deprecation)
- Frontend: **6 bestanden**, 0 fehlgeschlagen (4 Testdateien)
- Frontend-Build: **erfolgreich** (`tsc -b && vite build`, 0 Fehler; 937.86 kB JS, 31.37 kB CSS)
- Frontend-Lint: **1 Warnung** (`button.tsx` fast-refresh, kosmetisch)
- Import-Check: `app.main` importierbar

## 4. Abnahmekriterien

1. Foreign Keys enforced auf jeder SQLite-Verbindung — **ja**
2. Transaktion mit unbekanntem Konto/Kategorie wird abgelehnt (404/400) — **ja**
3. Archivierte Kategorie kann nicht verwendet werden — **ja**
4. Kategorie-Typ muss zur Buchung passen — **ja**
5. Stornierte Transaktionen und ihre Storno-Buchungen erscheinen nicht in Berichten/Budget — **ja**
6. `transaction.created`-Event wird bei Create und Reversal emittiert — **ja**
7. Plugin-Registry ist idempotent pro App (keine doppelten Routen) — **ja**
8. Investment-Trade ist atomar (kein Trade bei unzureichendem Bestand) — **ja**
9. Gewichteter Durchschnittspreis rundet HALF_UP auf ganze Rappen — **ja**
10. Alle Tests grün — **ja**

## 5. Abweichungen / Risiken

- Phase 5 ist nicht als geplante Phase in `docs/` vorgesehen; dieser Bericht dokumentiert nachträglich die Hardening-Arbeit.
- Bundle > 500 kB (Recharts) — Code-Splitting weiterhin offen (seit Phase 4).
- Keine Formularvalidierung (Zod) und keine Toast-Benachrichtigungen (seit Phase 3 offen).
- Alle Änderungen sind uncommitted (nur 1 Baseline-Commit im Repo) — Freigabe für Commit erforderlich (AGENTS.md §10).
- Plugin-Tabellen werden beim Register per `create_all` angelegt; keine Migrationen (AGENTS.md: keine Migration ohne Freigabe).

## 6. Nicht getan

- PHASENBERICHT_5 war bis jetzt nicht vorhanden (jetzt erstellt).
- Commit der Hardening-Änderungen (wartet auf Freigabe).
- Zod-Validierung, Toasts, Code-Splitting.

## 7. Empfehlung

Hardening-Arbeit ist abgeschlossen und getestet. Nächste Schritte: (a) Freigabe für Commit der 17 geänderten Dateien, (b) anschließend Phase 6 (Validierung/Toasts) oder Phase 5-Dokumentation abschließen.
