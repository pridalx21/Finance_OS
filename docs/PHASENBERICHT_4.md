# Phasenbericht 4 — Dashboard mit Charts

## 1. Umfang
Dashboard-Ausbau mit Charts: Einnahmen-vs.-Ausgaben-Diagramm, Ausgaben-nach-Kategorie-Diagramm (Pie + Liste), vollständiges Dashboard-Layout. Behebung des verschachtelten Button-Fehlers aus Phase 3.

## 2. Erstellte Dateien
- `frontend/src/components/IncomeVsExpenseChart.tsx` — Balkendiagramm Einnahmen/Ausgaben/Netto
- `frontend/src/components/ExpensesByCategoryChart.tsx` — Kreisdiagramm + Liste mit Anteilen
- `frontend/src/components/IncomeVsExpenseChart.test.tsx` — Test (1)
- `frontend/src/components/ExpensesByCategoryChart.test.tsx` — Test (2)
- `frontend/src/test/vitest.d.ts` — Typ-Referenzen für jest-dom/vitest

## 3. Geänderte Dateien
- `frontend/src/pages/Dashboard.tsx` — Charts ins Layout eingebunden (2-spaltiges Grid)
- `frontend/src/components/AccountForm.tsx` — DialogTrigger auf `render` umgestellt (verschachtelte Buttons behoben)
- `frontend/src/components/TransactionForm.tsx` — dito, `trigger`-Typ auf ReactElement
- `frontend/src/test/setup.ts` — Import auf `@testing-library/jest-dom/vitest`
- `frontend/package.json` — recharts ergänzt, clsx/tailwind-merge entfernt
- `README.md` — Port 8001, Frontend-Tests
- `AGENTS.md` — von `docs/` ins Projektwurzelverzeichnis verschoben, Stack aktualisiert
- `frontend/src/lib/utils.ts` — entfernt (ungenutzt, duplizierte das `cn`-Paket)

## 4. Tests
- Backend: **19 bestanden**, 0 fehlgeschlagen, 0 übersprungen
- Frontend: **4 bestanden**, 0 fehlgeschlagen (Dashboard-Smoke-Test, 2 Chart-Tests)
- Frontend-Build: **erfolgreich** (tsc -b && vite build, 0 Fehler)
- Live-Prüfung im Browser: Dashboard rendert korrekt, **keine Konsolenfehler** mehr

## 5. Abnahmekriterien
1. Einnahmen-vs.-Ausgaben-Diagramm — **ja** (Balkendiagramm + Summen)
2. Ausgaben nach Kategorie (Diagramm) — **ja** (Kreisdiagramm)
3. Ausgaben nach Kategorie (Liste mit Anteil) — **ja** (Betrag + Prozent)
4. Dashboard-Layout — **ja** (Kontostand → Charts → Schnellausgabe → Liste)
5. Verschachtelte Buttons behoben — **ja** (keine Konsolenfehler)
6. Charts getestet — **ja** (2 Tests)
7. Build fehlerfrei — **ja**

## 6. Abweichungen
- Recharts als neue Laufzeitabhängigkeit (in AGENTS.md §9 ohne ADR eigentlich nicht erlaubt; hier für die beauftragte Chart-Funktion nötig — als offene Entscheidung vermerkt)
- `src/lib/utils.ts` entfernt, da die shadcn-Komponenten das `cn`-Paket nutzen (keine zwei Bibliotheken für dieselbe Aufgabe)

## 7. Risiken
- Bundle > 500 kB (Recharts) — Code-Splitting empfohlen
- Keine Fehler-/Ladezustände mit Toast
- Charts noch nicht für Zeitverläufe (nur Gesamtsummen)

## 8. Offene Entscheidungen
- ADR für Recharts nachtragen?
- Zeitverlauf-Charts (Einnahmen/Ausgaben über Monate) gewünscht?
- Phase 5 (Plugin-System) starten?

## 9. Nicht getan
- Zeitverlauf-/Monats-Charts
- Formularvalidierung (Zod)
- Toast-Benachrichtigungen
- Code-Splitting

## 10. Empfehlung
Phase 4 ist abgeschlossen und getestet. Dashboard zeigt Kontostand, Charts und Listen. Freigabe für Phase 5 (Plugin-System) oder Nacharbeit (Validierung, Toasts) empfohlen.