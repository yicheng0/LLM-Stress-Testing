param(
    [string]$BackendUrl = "http://127.0.0.1:8000",
    [string]$FrontendUrl = "http://127.0.0.1:5173",
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"

function Pass($Message) {
    Write-Host "[PASS] $Message" -ForegroundColor Green
}

function Warn($Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Fail($Message) {
    Write-Host "[FAIL] $Message" -ForegroundColor Red
    exit 1
}

function Require-Path($Path) {
    if (-not (Test-Path $Path)) {
        Fail "Missing required path: $Path"
    }
    Pass "Found $Path"
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

Require-Path "backend\app\main.py"
Require-Path "backend\requirements.txt"
Require-Path "frontend\package.json"
Require-Path "frontend\vite.config.js"
Require-Path ".env.example"

if (Test-Path "data") {
    Pass "Found data directory"
} else {
    Warn "data directory does not exist yet; backend startup will create the SQLite parent directory when needed"
}

if (Test-Path "results") {
    Pass "Found results directory"
} else {
    Warn "results directory does not exist yet; test runs will create result artifacts when needed"
}

try {
    $health = Invoke-RestMethod -Uri "$BackendUrl/api/health" -Method Get -TimeoutSec 5
    if ($health.status -ne "ok") {
        Fail "Backend health returned unexpected status: $($health.status)"
    }
    Pass "Backend health is ok at $BackendUrl/api/health"
} catch {
    Fail "Backend health check failed at $BackendUrl/api/health: $($_.Exception.Message)"
}

try {
    $tests = Invoke-RestMethod -Uri "$BackendUrl/api/tests?page=1&page_size=1" -Method Get -TimeoutSec 5
    if ($null -eq $tests.total -or $null -eq $tests.items) {
        Fail "Backend tests endpoint returned an unexpected shape"
    }
    Pass "Backend tests endpoint is readable"
} catch {
    Fail "Backend tests endpoint failed: $($_.Exception.Message)"
}

if (-not $SkipFrontend) {
    try {
        $response = Invoke-WebRequest -Uri $FrontendUrl -Method Get -TimeoutSec 5
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            Fail "Frontend returned HTTP $($response.StatusCode)"
        }
        Pass "Frontend is reachable at $FrontendUrl"
    } catch {
        Fail "Frontend check failed at ${FrontendUrl}: $($_.Exception.Message)"
    }
} else {
    Warn "Frontend check skipped"
}

Pass "Smoke check completed without creating a test task"
