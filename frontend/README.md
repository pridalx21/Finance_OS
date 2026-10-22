# Finance OS Frontend

React 19, TypeScript, Vite, Tailwind CSS v4 und shadcn/ui (Base UI).

## Entwicklung

```bash
npm install
npm run dev
```

Laeuft auf http://localhost:5173. Der Vite-Proxy leitet `/api` an das Backend
auf http://localhost:8001 weiter (siehe `vite.config.ts`).

## Tests und Build

```bash
npm run test
npm run build
npm run lint
```

## Struktur

- `src/pages/` — Seiten (Dashboard, Transaktionen, Berichte, Investments, Budgets)
- `src/components/` — wiederverwendbare UI-Komponenten
- `src/services/api.ts` — API-Client
- `src/types/` — TypeScript-Typen

Das Backend muss fuer API-Aufrufe auf Port 8001 laufen. Port 8000 gehoert dem
Trading Desk und wird von Finance OS nicht verwendet.
