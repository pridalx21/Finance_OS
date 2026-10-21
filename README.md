# Finance OS

Persönliches Finanzsystem — modulares, erweiterbares Design.

## Features (v1.0)

- Konto-Verwaltung (CHF)
- Einnahmen-Eingabe
- Ausgaben-Eingabe nach Kategorien (Schnellzugriff)
- Kontostand-Berechnung
- Ausgaben nach Kategorie (Bericht)
- Moderne React-Oberfläche (in Entwicklung)

## Architektur

- **Backend:** Python (FastAPI) + SQLite
- **Frontend:** React + TypeScript + Vite (in Entwicklung)
- **Plugin-System:** Erweiterbar für Aktien, Geschäfte, Budgets, Auth

## Schnellstart

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Das Frontend läuft auf http://localhost:5173 und leitet `/api` an das Backend auf Port 8001 weiter.

## API-Dokumentation

Nach dem Start des Backends: http://localhost:8001/docs

## Tests

```bash
cd backend
pytest -v

cd ../frontend
npm run test
```

## Projektstruktur

```
Finance_OS/
├── backend/          # FastAPI Backend
├── frontend/         # React Frontend (in Entwicklung)
├── docs/             # Dokumentation
├── data/             # SQLite Datenbank
└── .gitignore
```
