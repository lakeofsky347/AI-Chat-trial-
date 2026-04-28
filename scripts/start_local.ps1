param(
    [string]$ClientFile = "flet_client.py",
    [switch]$SkipClient,
    [int]$StartupTimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$parentRoot = (Resolve-Path (Join-Path $projectRoot "..")).Path

$candidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $parentRoot ".venv\Scripts\python.exe")
)
if ($env:VIRTUAL_ENV) {
    $candidates += (Join-Path $env:VIRTUAL_ENV "Scripts\python.exe")
}

$pythonExe = $null
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
        $pythonExe = $candidate
        break
    }
}
if (-not $pythonExe) {
    throw "Python venv not found. Checked:`n - $($candidates -join "`n - ")"
}

if (-not (Test-Path (Join-Path $projectRoot $ClientFile))) {
    throw "Client file not found: $ClientFile"
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -Method GET -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "$Name is ready: $Url" -ForegroundColor DarkGreen
                return
            }
        }
        catch {}
        Start-Sleep -Milliseconds 400
    }

    throw "$Name is not ready within ${TimeoutSeconds}s: $Url"
}

function Assert-PortFree {
    param([Parameter(Mandatory = $true)][int]$Port)

    $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $listeners) { return }

    $pids = ($listeners | Select-Object -ExpandProperty OwningProcess | Sort-Object -Unique)
    throw "Port $Port is already in use by PID(s): $($pids -join ', '). Stop existing process and retry."
}

$appCmd = @"
Set-Location '$projectRoot'
& '$pythonExe' -m uvicorn main:app --host 127.0.0.1 --port 8000
"@

$clientCmd = @"
Set-Location '$projectRoot'
& '$pythonExe' '$ClientFile'
"@

Assert-PortFree -Port 8000

$appProc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $appCmd -WindowStyle Normal -PassThru
Wait-HttpReady -Url "http://127.0.0.1:8000/api/settings" -Name "app" -TimeoutSeconds $StartupTimeoutSeconds

if (-not $SkipClient) {
    $clientProc = Start-Process powershell -ArgumentList "-NoExit", "-Command", $clientCmd -WindowStyle Normal -PassThru
}

Write-Host "Python: $pythonExe" -ForegroundColor Cyan
Write-Host "Started: app(8000, pid=$($appProc.Id))" -ForegroundColor Green
if (-not $SkipClient) {
    Write-Host "Started: client($ClientFile, pid=$($clientProc.Id))" -ForegroundColor Green
}
else {
    Write-Host "Client start skipped (-SkipClient)." -ForegroundColor Yellow
}
