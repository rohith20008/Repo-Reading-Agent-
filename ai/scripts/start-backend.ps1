param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 5173
)

# Starts only the CODEMIND backend. Start Ollama separately with backend\scripts\start_ollama.ps1.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$listener = Get-NetTCPConnection -LocalPort $BackendPort -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owners = @($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "Backend port $BackendPort is already in use (PID $owners). It was left untouched."
}

Set-Location "$root\backend"
if ($FrontendPort -ne 5173) {
    $configuredCors = $env:CODEMIND_CORS
    if (-not $configuredCors -and (Test-Path '.env')) {
        $corsLine = Get-Content '.env' | Where-Object { $_ -match '^\s*CODEMIND_CORS\s*=' } | Select-Object -First 1
        if ($corsLine) {
            $configuredCors = ($corsLine -split '=', 2)[1].Trim().Trim('"').Trim("'")
        }
    }
    $origins = @(
        'http://localhost:5173',
        'http://127.0.0.1:5173'
    )
    $origins += @($configuredCors -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $origins += @(
        "http://localhost:$FrontendPort",
        "http://127.0.0.1:$FrontendPort"
    )
    $env:CODEMIND_CORS = ($origins | Select-Object -Unique) -join ','
}
$python = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
& $python -m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort
