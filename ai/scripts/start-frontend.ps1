param(
    [ValidateRange(1, 65535)]
    [int]$Port = 5173,
    [string]$BackendUrl = 'http://127.0.0.1:8000'
)

# Starts only the CODEMIND frontend and refuses to bind to a different project’s port.
$ErrorActionPreference = 'Stop'
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $owners = @($listener | Select-Object -ExpandProperty OwningProcess -Unique) -join ', '
    throw "Frontend port $Port is already in use (PID $owners). It was left untouched."
}
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\agent_pro"
$env:VITE_API_URL = $BackendUrl.TrimEnd('/')
& npm.cmd run dev -- --host 127.0.0.1 --port $Port --strictPort
