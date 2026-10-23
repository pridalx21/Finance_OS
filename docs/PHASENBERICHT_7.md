# Phasenbericht 7 - V1-Stabilisierung (Finance OS)

## 1. Ausgangszustand

- Backend: 64 Tests bestanden, Frontend: 6 Tests bestanden, Build grün.
- Drei konkurrierende Schulden-Implementierungen (`debts.py`, `_debt.py`,
  `_schulden.py`) mit getrennten Tabellen und Routen.
- Kein Migrationssystem: `Base.metadata.create_all()` erzeugte nur fehlende
  Tabellen, bestehende Tabellen wurden nie verändert.
- Die Tests liefen gegen die Datenbank des Benutzers (`data/finance.db`),
  weil `init_db()` im Application-Lifespan den Produktions-Engine benutzte.

## 2. Bestandsaufnahme (Phase A)

### A. Bestätigte Fehler

| # | Fehler | Fundstelle | Auswirkung |
|---|--------|------------|------------|
| 1 | Zahlungen hatten keinen Idempotenzschlüssel | `plugins/debts.py` | Doppelte Rückzahlung verringerte die Restschuld doppelt |
| 2 | Zahlungen waren nie mit einer Buchung verknüpft | `plugins/debts.py` | Rückzahlungen wirkten sich auf keinen Kontostand aus |
| 3 | Zahlungen konnten nicht storniert werden | `plugins/debts.py` | Eine Fehlbuchung blieb dauerhaft wirksam |
| 4 | `remaining_cents` wurde inkrementell gepflegt | `plugins/debts.py` | Eine Betragsänderung nach Zahlungen zerstörte die Invariante |
| 5 | Idempotenzschlüssel ohne Konflikterkennung | `plugins/debts.py`, `plugins/reconciliation.py` | Abweichender Inhalt lieferte stillschweigend das alte Ergebnis |
| 6 | Stornierte Schulden zählten als "offen" | `plugins/debts.py` | `open_debt_cents` war auf der echten Datenbank um 123.45 CHF zu hoch |
| 7 | Datum nicht im Idempotenz-Vergleich | `services/transaction_service.py` | Gleicher Schlüssel, anderes Datum → stillschweigend alte Buchung |
| 8 | Historischer Kontostand durch spätere Storno verfälscht | `plugins/reconciliation.py` | Abgleich vom 31.01. verlor eine Januar-Buchung, die erst im März storniert wurde |
| 9 | Kein Migrationssystem | `app/db/database.py` | Neue Spalten fehlten in bestehenden Datenbanken |
| 10 | Tests schrieben in die Benutzerdatenbank | `tests/conftest.py` | Ein Testlauf veränderte Schema und Daten von `data/finance.db` |
| 11 | Doppelte Schulden-Plugins | `plugins/_debt.py`, `plugins/_schulden.py` | Verwirrung, tote Tabellen `plugin_debt_*`, `plugin_schulden_*` |
| 12 | Float-Arithmetik für Geldbeträge im Frontend | `AccountForm`, `QuickExpense`, `TransactionForm` | `8.115` → 811 statt 812 Rappen |
| 13 | Abgleich zeigte immer den heutigen Stand | `ReconciliationManager.tsx` | Angezeigte Differenz wich vom gespeicherten Abgleich ab |
| 14 | Keine Fehleranzeigen im Frontend | mehrere Komponenten | Serverfehler blieben für den Benutzer unsichtbar |

### B. Risiken, die durch Tests verifiziert wurden

- Fremdschlüssel auf SQLite (`PRAGMA foreign_keys=ON`).
- Atomarität von Investoren-Trades und Plugin-Registrierung.
- Verhalten der Berichte bei stornierten Buchungen.
- Historische Reproduzierbarkeit der Abgleiche.

### C. Bereits korrekt implementiert (nicht geändert)

- `AccountService.balance` mit Anfangssaldo und `active_transactions`.
- Investoren-Trades: atomar, gewichteter Durchschnitt HALF_UP.
- Plugin-Registry: idempotent pro App, Modul-Reuse, Auto-Discovery.
- Event-Bus `transaction.created`.
- Kategorieprüfung (archiviert, Typ-Match) in der Buchungserfassung.

## 3. Durchgeführte Änderungen

### Phase B - Schulden fachlich korrekt

- `plugins/debts.py` neu aufgebaut (Service-Schicht `DebtService`, Router,
  Modelle, Schemas).
- Restbetrag wird **immer neu berechnet**
  (`Betrag − gültige Zahlungen + dokumentierte Korrektur`), nicht inkrementell
  gepflegt. `correction_cents` hält eine ausdrücklich dokumentierte
  manuelle Korrektur fest.
- Strikte Validierung: Typ, Status, Betrag > 0, Gegenpartei erforderlich,
  Fälligkeitsdatum, Konto vorhanden und nicht archiviert.
- Idempotenzschlüssel für Zahlungen (eindeutiger DB-Index) inklusive
  Konflikterkennung (HTTP 409) über einen Payload-Fingerprint.
- Zahlung optional als Buchung verknüpfbar (`create_transaction`): eigene
  Schuld → Ausgabe, Forderung → Einnahme. Ohne Verknüpfung bleibt
  `transaction_id` leer ("ohne Kontobewegung").
- Zahlung, Buchung und Restbetrag werden in einer Transaktion gespeichert
  (`TransactionService.create(..., commit=False)`).
- Storno einer Zahlung: bleibt in der Historie sichtbar
  (`cancelled_at`), stellt den Restbetrag wieder her und storniert eine
  verknüpfte Buchung.
- Summen: Forderungen und Verbindlichkeiten getrennt, `net_open_cents` als
  Netto, stornierte Schulden zählen nicht als offen.

### Phase C - Kontostände und Buchungen

- `effective_transactions(transactions, as_of)` als **einzige**
  Berechnungsregel im Projekt (Konten, Berichte, Budgets, Schulden,
  Abgleich). `active_transactions()` bleibt als Alias erhalten.
- Idempotenz über `idempotency_fingerprint` (SHA-256 des Client-Payloads);
  Datum und Beschreibung sind damit vollständig im Vergleich. Zeilen ohne
  Fingerprint (Altbestand) werden feldweise verglichen.
- Storno-Buchung verweist in beide Richtungen (`reversed_by` /
  `reverses_id`).
- `TransactionService` kann ohne Commit arbeiten (`commit=False`).

### Phase D - Kontostandsabgleich

- Historischer Stichtag korrigiert: eine Stornierung wirkt erst ab dem
  Datum der Stornierung; eine Januar-Buchung, die im März storniert wurde,
  zählt am 31.01. noch.
- Abgleich speichert zusätzlich die zugrunde liegenden Buchungen
  (`basis_transaction_ids`) → reproduzierbarer Snapshot.
- `GET /api/reconciliation/expected-balance` liefert den Systemkontostand
  für einen Stichtag (Grundlage der Anzeige im Frontend).
- Idempotenzschlüssel mit Konflikterkennung.

### Phase E - Datenbank und Migrationen

- Neu: `app/db/migrations.py` - versionierte, idempotente Migrationen mit
  Tabelle `schema_migrations`, 4 Migrationen (siehe README).
- Neu: `app/db/backup.py` - Sicherung/Wiederherstellung/Prüfung per CLI.
- Fremdschlüssel, Indizes, eindeutiger Idempotenzschlüssel der Zahlungen.
- Alt-Tabellen werden nur gelöscht, wenn sie leer sind.

### Phase F - Frontend

- Neu: `src/lib/money.ts` (exakte Betragseingabe ohne Float),
  `src/lib/idempotency.ts`.
- `DebtManager`: Pflichtangaben, Fehleranzeige, Zahlungsliste, Storno der
  Zahlung, Wahl "mit/ohne Buchung", Ladezustände.
- `ReconciliationManager`: Systemkontostand des gewählten Stichtags,
  Fehleranzeige.
- `AccountForm`, `QuickExpense`, `TransactionForm`: exakte Betragseingabe,
  Fehleranzeige.
- API-Client und Typen um die neuen Felder und Endpunkte erweitert.

### Weitere Bereinigung

- `plugins/_debt.py` und `plugins/_schulden.py` entfernt (inaktiv, nicht
  importiert, Tabellen leer, Daten in `plugin_debts_debts`).
- Tests isoliert: der Application-Engine zeigt im Test auf die
  In-Memory-Datenbank, `data/finance.db` wird nicht mehr angefasst.

## 4. Tests

Neu: `tests/test_debts.py` (39), `tests/test_reconciliation.py` (17),
`tests/test_migrations.py` (10), `tests/test_backup.py` (8);
`tests/test_transactions.py` um 8 Tests erweitert.
Frontend: `src/lib/money.test.ts` (17), `src/components/DebtManager.test.tsx` (6).

| Lauf | Ergebnis |
|------|----------|
| `backend: pytest -q` | **146 bestanden**, 0 fehlgeschlagen |
| `frontend: npm run test` | **29 bestanden**, 0 fehlgeschlagen (6 Dateien) |
| `frontend: npm run build` | erfolgreich (tsc + vite) |
| `frontend: npm run lint` | 1 kosmetische Warnung (`ui/button.tsx`, vorbestehend) |
| Live-Test gegen eine Kopie von `data/finance.db` | alle Prüfungen bestanden |

## 5. Abnahmekriterien

1. Nur eine verbindliche Schulden-Implementierung - **ja** (`plugins/debts.py`).
2. Restbetrag = Betrag − gültige Zahlungen - **ja** (immer neu berechnet).
3. Überzahlung, ungültiger Betrag, unbekannter Typ/Status abgelehnt - **ja**.
4. Zahlung idempotent, Konflikt bei abweichendem Inhalt - **ja**.
5. Zahlung + Buchung + Restbetrag atomar - **ja**.
6. Zahlung stornierbar, Historie bleibt erhalten - **ja**.
7. Einheitliche Kontostandslogik in allen Modulen - **ja**
   (`effective_transactions`).
8. Idempotenz der Buchungen inkl. Datum - **ja**.
9. Historischer Stichtag korrekt, spätere Storno wirkungslos für die
   Historie - **ja**.
10. Abgleich erzeugt keine Buchung und bleibt nachvollziehbar - **ja**.
11. Migrationen für leere und bestehende Datenbanken - **ja**.
12. Backup/Wiederherstellung praktisch getestet - **ja**.
13. Tests berühren die Benutzerdatenbank nicht - **ja**.
14. Frontend: Kernabläufe bedienbar, mit Lade- und Fehlerzuständen - **ja**.

## 6. Verbleibende Risiken und Einschränkungen

- Anlegen von Konto/Kategorie ist nicht idempotent (kein Schlüssel auf
  diesem Schreibpfad).
- Ein Storno trägt das Storno-Datum; rückdatierte Stornos werden nicht
  unterstützt.
- Keine Zins-/Ratenberechnung, keine Gebührenaufteilung.
- Keine Rückwärtsmigration; vor einem Update mit Schemaänderungen ist eine
  Sicherung empfohlen.
- Bundle-Grösse im Frontend > 500 kB (Recharts).

## 7. Geänderte Dateien

Backend (neu): `app/db/migrations.py`, `app/db/backup.py`, `tests/test_debts.py`,
`tests/test_reconciliation.py`, `tests/test_migrations.py`,
`tests/test_backup.py`.
Backend (geändert): `app/db/database.py`, `app/main.py`,
`app/models/transaction.py`, `app/schemas/transaction.py`,
`app/services/transaction_service.py`, `app/services/account_service.py`,
`plugins/debts.py`, `plugins/reconciliation.py`, `tests/conftest.py`,
`tests/test_transactions.py`, `tests/test_plugins_integration.py`.
Backend (entfernt): `plugins/_debt.py`, `plugins/_schulden.py`.
Frontend (neu): `src/lib/money.ts`, `src/lib/money.test.ts`,
`src/lib/idempotency.ts`, `src/components/DebtManager.test.tsx`.
Frontend (geändert): `src/types/index.ts`, `src/services/api.ts`,
`src/components/DebtManager.tsx`, `src/components/ReconciliationManager.tsx`,
`src/components/AccountForm.tsx`, `src/components/QuickExpense.tsx`,
`src/components/TransactionForm.tsx`.
Doku: `README.md`, `docs/PHASENBERICHT_7.md`.

## 8. Empfehlung

V1 ist fachlich abgeschlossen: Kontostände, Stornierungen, Schulden,
Rückzahlungen und Kontostandsabgleich sind konsistent und getestet. Vor dem
Produktivbetrieb: Anwendung neu starten (die Migrationen laufen dann
automatisch) und einmalig die Oberfläche im Browser durchklicken.
