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

# Abhaengigkeiten installieren
Write-Host "Installiere Abhaengigkeiten..."
pip install -q -r requirements.txt

# Datenbank-Verzeichnis erstellen
$dataDir = Join-Path $projectRoot "data"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Path $dataDir | Out-Null
}

# Port 8001 pruefen; niemals einen fremden Prozess beenden.
$existing = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Port 8001 ist bereits belegt. Start abgebrochen."
    exit 1
}

# Server starten
$python = Join-Path $backendDir ".venv\Scripts\python.exe"
Write-Host "Starte Finance OS Backend auf http://127.0.0.1:8001"
Write-Host "API-Docs: http://127.0.0.1:8001/docs"
$process = Start-Process -FilePath $python `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--reload", "--host", "127.0.0.1", "--port", "8001" `
    -NoNewWindow -PassThru

# Health-Check anzeigen, danach am Prozess bleiben.
$healthy = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8001/api/health" -TimeoutSec 2
        Write-Host "Health: $($health.status)"
        $healthy = $true
        break
    } catch {
    }
}
if (-not $healthy) {
    Write-Host "Health-Check fehlgeschlagen (Backend laeuft eventuell noch)."
}

Wait-Process -Id $process.Id
