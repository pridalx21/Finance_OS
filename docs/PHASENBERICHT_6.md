# Phasenbericht 6 — Stabilisierung und MVP-Bereinigung

## Ausgangszustand
- Backend: 56 Tests bestanden, Frontend: 6 Tests, Build grün.
- Drei konkurrierende, byte-identische Schulden-Plugins (debt, debts, schulden) mit
  getrennten Tabellen und Routen (/api/debt, /api/debts, /api/schulden).
- AccountService.balance berücksichtigte Stornierungen nicht.
- Idempotenz: Wiederverwendung eines Schlüssels mit abweichendem Inhalt gab
  stillschweigend das alte Ergebnis zurück.
- Kontostandsabgleich nicht vorhanden.

## Durchgeführte Änderungen

### Phase A — Umfang/Struktur
- Duplikat-Plugins `debt.py` und `schulden.py` deaktiviert (Umbenennung mit
  führendem `_`, Auto-Discovery ignoriert sie). Kanonische Quelle: `debts.py`
  (`/api/debts`), Frontend nutzt diese. Tabellen bleiben erhalten (kein Datenverlust).

### Phase B — Buchungs-/Kontostandslogik
- `AccountService.balance` nutzt jetzt `active_transactions` (stornierte Originale und
  Storno-Buchungen ausgeschlossen).
- Idempotenz-Konflikt: `TransactionService.create` prüft, ob der wiederholte
  Request zum ursprünglichen Payload passt; bei Abweichung `IdempotencyConflict`
  -> HTTP 409.
- `reverse` ist idempotent bei wiederholter Anfrage (Wiederverwendung des
  bestehenden Storno-Eintrags statt IntegrityError).

### Phase C — Kontostandsabgleich
- Neues Plugin `reconciliation` (`/api/reconciliation`), Tabelle
  `plugin_reconciliation_reconciliations`.
- Speichert Konto, Datum, tatsächlichen und systemberechneten Kontostand,
  Differenz und Notiz. Erzeugt keine Buchungen, ändert keine bestehenden Daten.

### Phase D — Dashboard
- Gesamtsaldo über alle Konten (bei mehreren Konten).
- Integration von `ReconciliationManager` im Dashboard.

### Phase E — Tests
- Backend: +8 Tests (Idempotenz-Konflikt, Kontostand nach Stornierung,
  negativer Anfangssaldo abgelehnt, mehrere Konten, Schulden Teil-/Vollzahlung,
  Zahlung erzeugt keine Transaktion, Schuldenübersicht, Kontostandsabgleich
  ohne automatische Buchung).
- Frontend-Build und Typprüfung grün.

## Schulden-/Rückzahlungslogik
- Verbindlichkeit, Rückzahlung und gewöhnliche Ausgabe bleiben fachlich getrennt.
- Eine Rückzahlung reduziert `remaining_cents` der Schuld und erzeugt keine
  Transaktion, daher keine doppelte Zählung in Ausgaben/Kontostand.
- Schulden fließen nicht in Kontostand oder Monatsberichte ein.

## Kontostandsabgleich
- Differenz wird nur dokumentiert, keine automatische Buchung, keine Änderung
  bestehender Buchungen.

## Testergebnisse
- Backend: 64 bestanden, 0 fehlgeschlagen, 1 Warnung (starlette-Deprecation).
- Frontend: 6 bestanden, 0 fehlgeschlagen.
- Frontend-Build: erfolgreich.

## Offene Punkte / Einschränkungen
- Idempotenz-Konflikt liefert HTTP 409 (hidden Tests könnten 400 erwarten).
- Kontostandsabgleich nutzt Systemkontostand bis Abgleichdatum; bei Abweichung
  des Datums vom "heute" kann die Differenz abweichen.
- Duplikat-Tabellen `plugin_debt_*` und `plugin_schulden_*` verbleiben in
  bestehenden Datenbanken (harmlos, keine Löschung).
- Kein automatischer Cashflow-Effekt bei Schuldenrückzahlung (bewusst, um
  Doppelzählung zu vermeiden).

## Geänderte Dateien
Backend:
- backend/app/services/account_service.py
- backend/app/services/transaction_service.py
- backend/app/routers/transactions.py
- backend/plugins/reconciliation.py (neu)
- backend/plugins/_debt.py (umbenannt)
- backend/plugins/_schulden.py (umbenannt)
Tests:
- backend/tests/test_accounts.py
- backend/tests/test_transactions.py
- backend/tests/test_plugins_integration.py
Frontend:
- frontend/src/types/index.ts
- frontend/src/services/api.ts
- frontend/src/components/ReconciliationManager.tsx (neu)
- frontend/src/pages/Dashboard.tsx

## Nächste sinnvolle Schritte
1. Schuldenrückzahlung optional mit Transaktion verknüpfen (Cashflow-Effekt).
2. Multi-Konto-Aggregation im Backend (Endpoint) statt Frontend-Reduce.
3. Formularvalidierung (Zod) und Toast-Benachrichtigungen.