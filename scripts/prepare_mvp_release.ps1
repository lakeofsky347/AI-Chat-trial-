param(
    [string]$OutputDir = "",
    [switch]$IncludeDocs
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $projectRoot "_release_mvp"
}

if (Test-Path -LiteralPath $OutputDir) {
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}
New-Item -ItemType Directory -Path $OutputDir | Out-Null

$whitelist = @(
    "app",
    "clients",
    "scripts/start_local.ps1",
    "main.py",
    "flet_client.py",
    "run_all_in_one.py",
    "requirements.txt",
    "README.md",
    ".env.local.example"
)

if ($IncludeDocs) {
    $whitelist += "docs/progress_snapshot_2026-04-12.md"
}

foreach ($relPath in $whitelist) {
    $src = Join-Path $projectRoot $relPath
    if (-not (Test-Path -LiteralPath $src)) {
        Write-Warning "Skip missing path: $relPath"
        continue
    }

    $dst = Join-Path $OutputDir $relPath
    $srcItem = Get-Item -LiteralPath $src
    if ($srcItem.PSIsContainer) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force
    } else {
        New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
    }
}

# Enforce forbidden paths are not bundled.
$forbidden = @(
    ".env.local",
    "data",
    ".git",
    "__pycache__"
)
foreach ($relPath in $forbidden) {
    $p = Join-Path $OutputDir $relPath
    if (Test-Path -LiteralPath $p) {
        throw "Forbidden path included in release bundle: $relPath"
    }
}

# Remove caches if any copied transitively.
Get-ChildItem -Path $OutputDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
Get-ChildItem -Path $OutputDir -Recurse -File -Include "*.pyc","*.pyo" -ErrorAction SilentlyContinue |
    Remove-Item -Force

# Secrets scan.
$rg = Get-Command rg -ErrorAction SilentlyContinue
if ($null -ne $rg) {
    $pattern = "sk-[A-Za-z0-9_-]{16,}|tvly-[A-Za-z0-9_-]{10,}|-----BEGIN (RSA|OPENSSH|PRIVATE) KEY-----"
    $hits = & $rg.Source -n -S $pattern $OutputDir
    if ($LASTEXITCODE -eq 0 -and $hits) {
        Write-Host $hits
        throw "Secret-like content detected in release bundle."
    }
}

$manifest = Join-Path $OutputDir "RELEASE_MANIFEST.txt"
Get-ChildItem -Path $OutputDir -Recurse -File |
    ForEach-Object {
        $_.FullName.Replace($OutputDir, "").TrimStart("\")
    } |
    Sort-Object |
    Set-Content -Path $manifest -Encoding UTF8

Write-Host "Release bundle prepared: $OutputDir" -ForegroundColor Green
Write-Host "Manifest: $manifest" -ForegroundColor Green
