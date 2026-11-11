param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 5173
)

# Starts CODEMIND only after confirming its selected ports are free.
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$root = Split-Path -Parent $here
foreach ($port in @($BackendPort, $FrontendPort)) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($listener) {
        $owners = @($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
        throw "Port $port is already in use (PID $owners). No process was started. Choose a free port; existing processes were left untouched."
    }
}

$backendScript = Join-Path $here 'start-backend.ps1'
$frontendScript = Join-Path $here 'start-frontend.ps1'
Start-Process powershell.exe -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $backendScript,
    '-BackendPort', "$BackendPort", '-FrontendPort', "$FrontendPort"
)
Start-Process powershell.exe -ArgumentList @(
    '-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $frontendScript,
    '-Port', "$FrontendPort", '-BackendUrl', "http://127.0.0.1:$BackendPort"
)

$apiUrl = "http://127.0.0.1:$BackendPort"
$frontendUrl = "http://127.0.0.1:$FrontendPort"
$backendReady = $false
$frontendReady = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if (-not $backendReady) {
        try {
            $health = Invoke-RestMethod "$apiUrl/api/health" -TimeoutSec 2
            $backendReady = $health.status -eq 'ok'
        } catch { }
    }
    if (-not $frontendReady) {
        try {
            $page = Invoke-WebRequest $frontendUrl -TimeoutSec 2 -UseBasicParsing
            $frontendReady = $page.StatusCode -eq 200 -and $page.Content -match 'CODEMIND|root'
        } catch { }
    }
    if ($backendReady -and $frontendReady) {
        break
    }
    Start-Sleep -Seconds 1
}
if (-not $backendReady -or -not $frontendReady) {
    throw "CODEMIND did not become ready. Backend ready: $backendReady ($apiUrl); frontend ready: $frontendReady ($frontendUrl). Check the two PowerShell windows."
}

Write-Host "CODEMIND backend: $apiUrl (health: $apiUrl/api/health)"
Write-Host "CODEMIND frontend: $frontendUrl"
Start-Process $frontendUrl
