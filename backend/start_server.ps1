# Start the ALAI backend using the venv Python (not the global Python311)
# Usage: .\start_server.ps1
Set-Location $PSScriptRoot
.\venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
