param(
    [Parameter(Position = 0)]
    [ValidateSet('start', 'stop', 'status')]
    [string]$Action = 'start'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeDir = Join-Path $PSScriptRoot '.runtime'
$statePath = Join-Path $runtimeDir 'dev.json'
$backendUrl = 'http://127.0.0.1:8000/api/v1/health'
$frontendUrl = 'http://127.0.0.1:5173'
$pythonPath = Join-Path $projectRoot 'backend\.venv\Scripts\python.exe'
$vitePath = Join-Path $projectRoot 'frontend\node_modules\vite\bin\vite.js'
$controlLock = $null

function Test-Port([int]$Port) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $pending.AsyncWaitHandle.WaitOne(300)) { return $false }
        try { $client.EndConnect($pending); return $true } catch { return $false }
    } finally { $client.Dispose() }
}

function Test-Http([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        if ($response.StatusCode -ne 200) { return $false }
        if ($Url.EndsWith('/api/v1/health')) {
            $health = $response.Content | ConvertFrom-Json
            return $health.status -eq 'ok' -and $health.service -eq 'paperassist-system'
        }
        return $true
    } catch { return $false }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath)) { return $null }
    $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ($saved.version -ne 1 -or $saved.project_root -ne $projectRoot) {
        throw 'Runtime state belongs to a different project or version. No process was stopped.'
    }
    foreach ($service in @($saved.services)) {
        if ($service.name -notin @('backend', 'frontend') -or $service.process_id -le 0) {
            throw 'Invalid runtime state. No process was stopped.'
        }
    }
    return $saved
}

function Save-State($State) {
    $temporary = $statePath + '.tmp'
    $State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $statePath -Force
}

function Get-OwnedProcess($Service) {
    $process = Get-Process -Id $Service.process_id -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    try {
        # Pin the OS handle before identity checks, so PID reuse cannot retarget Kill.
        $null = $process.Handle
        if ($process.HasExited) { return $null }
        $created = $process.StartTime.ToUniversalTime().ToString('o')
        if ($created -ne $Service.started_utc -or $process.Path -ne $Service.executable) {
            throw "PID identity changed for $($Service.name). Refusing to stop or reuse that process."
        }
    } catch {
        if ($process.HasExited) { return $null }
        throw
    }
    return $process
}

function Stop-Services($State) {
    # Validate every recorded identity before stopping anything. Never kill by port/name.
    foreach ($service in @($State.services)) { $null = Get-OwnedProcess $service }
    foreach ($service in @($State.services | Sort-Object name -Descending)) {
        $process = Get-OwnedProcess $service
        if ($null -eq $process) { continue }
        Stop-ProcessTree $process
    }
    if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
}

function Stop-ProcessTree([Diagnostics.Process]$Process) {
    if (-not ('PaperAssistProcessTree' -as [type])) {
        Add-Type -Path (Join-Path $PSScriptRoot 'process-tree.cs')
    }
    [PaperAssistProcessTree]::Stop($Process)
}

function Start-ServiceProcess([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$Directory) {
    # Paths are quoted for CreateProcess, never interpolated into cmd.exe commands.
    $argumentLine = ($Arguments | ForEach-Object {
        if ($_.Contains('"')) { throw 'A process argument contains an unsupported quote.' }
        '"' + $_ + '"'
    }) -join ' '
    $process = Start-Process -FilePath $Executable -ArgumentList $argumentLine `
        -WorkingDirectory $Directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $runtimeDir "$Name.stdout.log") `
        -RedirectStandardError (Join-Path $runtimeDir "$Name.stderr.log")
    try {
        return [pscustomobject]@{
            name = $Name
            process_id = $process.Id
            started_utc = $process.StartTime.ToUniversalTime().ToString('o')
            executable = $process.Path
        }
    } catch {
        # This is the fresh process handle, not a PID loaded from disk.
        if (-not $process.HasExited) {
            Stop-ProcessTree $process
        }
        throw
    }
}

function Wait-Ready($State) {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    while ([DateTime]::UtcNow -lt $deadline) {
        foreach ($service in @($State.services)) {
            if ($null -eq (Get-OwnedProcess $service)) {
                throw "$($service.name) exited during startup. Check the logs in $runtimeDir"
            }
        }
        if ((Test-Http $backendUrl) -and (Test-Http $frontendUrl) -and
            (Test-Http "$frontendUrl/api/v1/health")) { return }
        Start-Sleep -Milliseconds 400
    }
    throw "Startup health checks timed out. Check the logs in $runtimeDir"
}

function Show-Ready($State) {
    Write-Host "Frontend: $frontendUrl"
    Write-Host 'Backend:  http://127.0.0.1:8000'
    Write-Host "Logs:     $runtimeDir"
    foreach ($service in @($State.services)) {
        Write-Host "$($service.name) PID: $($service.process_id)"
    }
}

try {
    $null = New-Item -ItemType Directory -Path $runtimeDir -Force
    try {
        $controlLock = [IO.File]::Open((Join-Path $runtimeDir 'control.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch { throw 'Another launcher command is running. Retry when it finishes.' }
    $state = Read-State

    if ($Action -eq 'stop') {
        if ($null -eq $state) { Write-Host 'Stopped (no managed services).'; exit 0 }
        Stop-Services $state
        Write-Host 'Stopped the managed frontend and backend.'
        exit 0
    }

    if ($Action -eq 'status') {
        if ($null -eq $state) {
            Write-Host 'Stopped (no managed services).'
        } else {
            foreach ($service in @($state.services)) {
                $running = $null -ne (Get-OwnedProcess $service)
                Write-Host "$($service.name): running=$running, PID=$($service.process_id)"
            }
            Write-Host "Backend health: $(Test-Http $backendUrl)"
            Write-Host "Frontend health: $(Test-Http $frontendUrl)"
            Write-Host "API proxy health: $(Test-Http "$frontendUrl/api/v1/health")"
            Show-Ready $state
        }
        exit 0
    }

    if ($null -ne $state) {
        $running = @($state.services | Where-Object { $null -ne (Get-OwnedProcess $_) })
        if ($running.Count -eq 2 -and @($state.services).Count -eq 2) {
            Wait-Ready $state
            Write-Host 'Already running; reusing the managed services.'
            Show-Ready $state
            exit 0
        }
        if ($running.Count -gt 0) {
            throw 'Only some managed services are running. Run dev.cmd stop, then dev.cmd start.'
        }
        Remove-Item -LiteralPath $statePath
    }

    foreach ($port in @(8000, 5173)) {
        if (Test-Port $port) { throw "Port $port is occupied by an unmanaged service. Nothing was started or stopped." }
    }
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Missing backend virtual environment. Follow README setup first.' }
    if (-not (Test-Path -LiteralPath $vitePath)) { throw 'Missing frontend dependencies. Run npm.cmd --prefix frontend install first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'backend\.env'))) { throw 'Missing backend/.env. Follow README setup first.' }
    $nodePath = (Get-Command node.exe -ErrorAction Stop).Source

    $state = [pscustomobject]@{ version = 1; project_root = $projectRoot; services = @() }
    Save-State $state
    try {
        $state.services += Start-ServiceProcess 'backend' $pythonPath @(
            '-m', 'uvicorn', 'app.main:app', '--app-dir', 'backend',
            '--host', '127.0.0.1', '--port', '8000', '--no-proxy-headers'
        ) $projectRoot
        Save-State $state
        $state.services += Start-ServiceProcess 'frontend' $nodePath @(
            $vitePath, '--host', '127.0.0.1', '--port', '5173', '--strictPort'
        ) (Join-Path $projectRoot 'frontend')
        Save-State $state
        Wait-Ready $state
    } catch {
        $startupFailure = $_
        try { Stop-Services $state } catch { Write-Warning 'Cleanup was incomplete; runtime state retained. Run dev.cmd stop.' }
        throw $startupFailure
    }
    Write-Host 'Ready for manual acceptance testing.'
    Show-Ready $state
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    if ($null -ne $controlLock) { $controlLock.Dispose() }
}
