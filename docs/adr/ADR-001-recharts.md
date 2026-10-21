# ADR-001 — Recharts als Diagramm-Bibliothek

**Status:** Angenommen
**Datum:** 2026-10-21
**Betrifft:** Frontend (`frontend/`)

## Kontext

Das Dashboard (Phase 4) benötigt Diagramme:
- Einnahmen vs. Ausgaben (Balken)
- Ausgaben nach Kategorie (Kreis)
- Zeitverlauf Einnahmen/Ausgaben über Monate (Linien/Balken)

AGENTS.md §9 verlangt: keine neue Laufzeitabhängigkeit ohne ADR.

## Entscheidung

Es wird **Recharts** als Diagramm-Bibliothek verwendet.

- Paket: `recharts`
- Eingesetzt in: `IncomeVsExpenseChart`, `ExpensesByCategoryChart`, `MonthlyTrendChart`

## Begründung

| Kriterium | Recharts | Alternative (Chart.js) |
|-----------|----------|------------------------|
| React-Integration | native React-Komponenten | Wrapper nötig (`react-chartjs-2`) |
| Deklarativ | ja (JSX) | imperativ (Config-Objekt) |
| Responsive | `ResponsiveContainer` | manuell |
| TypeScript | mitgeliefert | über `@types` |
| Bundle | mittel | kleiner |

Recharts passt am besten zum deklarativen React-Stil des Projekts und vermeidet einen zusätzlichen Wrapper.

## Konsequenzen

- **Positiv:** Weniger Code, deklarativ, responsive, gute TS-Typen.
- **Negativ:** Bundle wächst (> 500 kB). Code-Splitting kann später nachgerüstet werden.
- **Neutral:** Nur eine Chart-Bibliothek im Projekt (AGENTS.md §9: keine zwei Bibliotheken für dieselbe Aufgabe).

## Alternativen (verworfen)

- **Chart.js** — imperativ, Wrapper nötig.
- **Eigene SVG-Diagramme** — zu viel Aufwand, fehleranfällig.
- **Nivo** — größer, komplexere API.
