# ALAI pre-push check script
# Runs all automated tests and the frontend build.
# Exit code 0 = all passed. Non-zero = something failed.
#
# Usage:  .\scripts\check.ps1

$root = Split-Path $PSScriptRoot -Parent
$failed = @()

function Step($label) {
    Write-Host ""
    Write-Host "========================================"
    Write-Host "  $label"
    Write-Host "========================================"
}

function Pass($label) { Write-Host "[PASS] $label" -ForegroundColor Green }
function Fail($label) {
    Write-Host "[FAIL] $label" -ForegroundColor Red
    $script:failed += $label
}

# --- 1. Backend router tests ---
Step "Backend router tests"
$venvPython = Join-Path $root "backend\venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Fail "venv not found -- run: cd backend; python -m venv venv; pip install -r requirements.txt"
} else {
    $testScript = Join-Path $root "backend\test_router.py"
    & $venvPython $testScript
    if ($LASTEXITCODE -eq 0) { Pass "Router bypass tests" }
    else { Fail "Router bypass tests" }
}

# --- 2. Frontend TypeScript check + production build ---
Step "Frontend build (tsc + vite build)"
$frontendDir = Join-Path $root "frontend"
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "node_modules missing -- running npm install..."
    Push-Location $frontendDir
    npm install
    Pop-Location
}
Push-Location $frontendDir
npm run build
if ($LASTEXITCODE -eq 0) { Pass "Frontend build" }
else { Fail "Frontend build -- fix TypeScript/Vite errors before pushing" }
Pop-Location

# --- 3. Backend import check ---
Step "Backend import check"
$importCheck = Join-Path $root "backend\scripts\import_check.py"
if (Test-Path $importCheck) {
    & $venvPython $importCheck
    if ($LASTEXITCODE -eq 0) { Pass "Backend imports" }
    else { Fail "Backend imports" }
} else {
    Write-Host "  (skipped -- backend\scripts\import_check.py not found)"
}

# --- Summary ---
Write-Host ""
Write-Host "========================================"
if ($failed.Count -eq 0) {
    Write-Host "  ALL CHECKS PASSED -- safe to push" -ForegroundColor Green
    Write-Host "========================================"
    exit 0
} else {
    Write-Host "  FAILED:" -ForegroundColor Red
    $failed | ForEach-Object { Write-Host "    - $_" -ForegroundColor Red }
    Write-Host "========================================"
    Write-Host "Fix the above before pushing." -ForegroundColor Yellow
    exit 1
}
