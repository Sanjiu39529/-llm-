$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$streamlit = Join-Path $projectRoot ".venv\Scripts\streamlit.exe"

if (-not (Test-Path (Join-Path $projectRoot ".env"))) {
    throw "Missing .env. Copy .env.example to .env and configure DATABASE_URL first."
}
if (-not (Test-Path $python) -or -not (Test-Path $streamlit)) {
    throw "Missing project virtual environment. Run pip install -r requirements.txt first."
}
if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 8000 is already in use. Close the existing API window first."
}
if (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue) {
    throw "Port 8501 is already in use. Close the existing Streamlit window first."
}

$apiCommand = "Set-Location -LiteralPath '$projectRoot'; & '$python' -m uvicorn backend.app.api:app --reload --port 8000"
$uiCommand = "Set-Location -LiteralPath '$projectRoot'; & '$streamlit' run frontend/app.py --server.port 8501"

Start-Process -FilePath powershell.exe -ArgumentList @("-NoExit", "-Command", $apiCommand)
Start-Sleep -Seconds 2
Start-Process -FilePath powershell.exe -ArgumentList @("-NoExit", "-Command", $uiCommand)
Start-Sleep -Seconds 3
Start-Process "http://127.0.0.1:8501"
