$ErrorActionPreference = 'Stop'

$ollamaHost = '127.0.0.1:11435'
$baseUrl = 'http://127.0.0.1:11435'
$requiredModels = @('qwen2.5-coder:3b', 'nomic-embed-text:latest')
$ollamaCommand = Get-Command ollama.exe -CommandType Application -ErrorAction SilentlyContinue
if (-not $ollamaCommand) {
    $ollamaCommand = Get-Command ollama -CommandType Application -ErrorAction SilentlyContinue
}
if (-not $ollamaCommand) {
    throw 'Ollama was not found on PATH. Install Ollama or add its installation folder to PATH.'
}
$ollamaPath = [System.IO.Path]::GetFullPath($ollamaCommand.Source)

function Get-DedicatedListeners {
    Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue
}

function Assert-OllamaOwnsListeners($listeners) {
    $owners = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($ownerId in $owners) {
        $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId" -ErrorAction SilentlyContinue
        if (-not $owner -or -not $owner.ExecutablePath -or $owner.Name -ne 'ollama.exe' -or
            [System.IO.Path]::GetFullPath($owner.ExecutablePath) -ine $ollamaPath -or
            $owner.CommandLine -notmatch '(^|\s)serve(\s|$)') {
            throw "Port 11435 is occupied by a process that is not the expected Ollama server (PID $ownerId). It was left untouched."
        }
    }
}

function Get-OllamaStatus {
    $version = Invoke-RestMethod -Uri "$baseUrl/api/version" -TimeoutSec 5
    $tags = Invoke-RestMethod -Uri "$baseUrl/api/tags" -TimeoutSec 5
    if (-not $version.version -or $null -eq $tags.models) {
        throw "The service at $baseUrl did not return valid Ollama version and model data."
    }
    return $tags
}

$listeners = @(Get-DedicatedListeners)
$serverProcess = $null
if ($listeners.Count -gt 0) {
    Assert-OllamaOwnsListeners $listeners
    Write-Host "Found the expected Ollama process on $baseUrl; reusing it."
} else {
    Write-Host "Starting CODEMIND's Ollama server on $ollamaHost."
    Write-Host 'The existing server on port 11434 and its model configuration will not be changed.'
    $hadOllamaHost = Test-Path Env:OLLAMA_HOST
    $previousOllamaHost = $env:OLLAMA_HOST
    try {
        $env:OLLAMA_HOST = $ollamaHost
        $serverProcess = Start-Process -FilePath $ollamaPath -ArgumentList 'serve' -PassThru
    } catch {
        throw "Could not start Ollama on ${ollamaHost}: $($_.Exception.Message)"
    } finally {
        if ($hadOllamaHost) {
            $env:OLLAMA_HOST = $previousOllamaHost
        } else {
            Remove-Item Env:OLLAMA_HOST -ErrorAction SilentlyContinue
        }
    }
}

$tags = $null
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $listeners = @(Get-DedicatedListeners)
    if ($listeners.Count -gt 0) {
        Assert-OllamaOwnsListeners $listeners
        try {
            $tags = Get-OllamaStatus
            break
        } catch {
            if ($attempt -eq 59) {
                throw "Ollama owns port 11435 but its API did not become ready at $baseUrl. $($_.Exception.Message)"
            }
        }
    } elseif ($attempt -eq 59) {
        $startedPid = if ($serverProcess) { $serverProcess.Id } else { 'unknown' }
        throw "Ollama did not start listening on port 11435 (started PID $startedPid). Check the Ollama installation and logs."
    }
    Start-Sleep -Seconds 1
}

$availableModels = @($tags.models | ForEach-Object { $_.name })
$missingModels = @($requiredModels | Where-Object { $_ -notin $availableModels })
if ($missingModels.Count -gt 0) {
    $missing = $missingModels -join ', '
    throw "CODEMIND's Ollama server is reachable at $baseUrl, but these models are missing: $missing. No model was downloaded. To pull a model in PowerShell, set `$env:OLLAMA_HOST='$ollamaHost'` in that shell and run `ollama pull <model>`. The other server on port 11434 was not changed."
}

$version = Invoke-RestMethod -Uri "$baseUrl/api/version" -TimeoutSec 5
Write-Host "CODEMIND Ollama is ready at $baseUrl (version $($version.version)); both required models are available."
if ($serverProcess) {
    Write-Host "Dedicated Ollama process PID: $($serverProcess.Id). It runs independently of the FastAPI backend."
}
