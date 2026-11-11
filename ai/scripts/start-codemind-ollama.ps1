# Compatibility entry point for the dedicated Ollama launcher.
$ErrorActionPreference = 'Stop'
$launcher = Join-Path (Split-Path -Parent $PSScriptRoot) 'backend\scripts\start_ollama.ps1'
& $launcher
