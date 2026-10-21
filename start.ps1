# Start Finance OS Backend
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDir = Join-Path $projectRoot "backend"

Set-Location $backendDir

# Virtual Environment erstellen, falls nicht vorhanden
if (-not (Test-Path ".venv")) {
    Write-Host "Erstelle Virtual Environment..."
    python -m venv .venv
}

# Aktivieren
& ".venv\Scripts\Activate.ps1"

# Abhängigkeiten installieren
Write-Host "Installiere Abhängigkeiten..."
pip install -q -r requirements.txt

# Datenbank-Verzeichnis erstellen
$dataDir = Join-Path $projectRoot "data"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
}

# Server starten
Write-Host "Starte Finance OS Backend auf http://localhost:8000"
Write-Host "API-Docs: http://localhost:8000/docs"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
