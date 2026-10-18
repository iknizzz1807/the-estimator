# Build the statically-exported Next.js frontend into frontend\out (Windows).
#
# The FastAPI backend serves frontend\out on the same port as /api/*, so this is
# the only frontend step needed for the single-service app (see DECISIONS D12).
# Requires Node.js on PATH; portable Node under %LOCALAPPDATA%\Temp\opencode is
# used automatically when present.
#
# Usage:
#   .\build.ps1              # npm ci (first run) + next build -> out\
#   .\build.ps1 -SkipInstall # build only, with the existing node_modules

param([switch]$SkipInstall)

$ErrorActionPreference = "Stop"

$nodeDir = Join-Path $env:LOCALAPPDATA "Temp\opencode\nodejs"
if (Test-Path $nodeDir) { $env:Path = "$nodeDir;$env:Path" }

$frontendDir = $PSScriptRoot
Set-Location $frontendDir

if (-not (Test-Path "node_modules\next\dist\bin\next")) {
    if ($SkipInstall) { throw "node_modules is missing; run without -SkipInstall first." }
    Write-Host "Installing dependencies (npm ci)..."
    npm ci
    if ($LASTEXITCODE -ne 0) { npm install; if ($LASTEXITCODE -ne 0) { throw "npm install failed" } }
}

Write-Host "Building static export (next build)..."
Remove-Item -Recurse -Force ".next", "out" -ErrorAction SilentlyContinue
node .\node_modules\next\dist\bin\next build
if ($LASTEXITCODE -ne 0) { throw "next build failed" }

if (Test-Path "out\index.html") { Write-Host "Done: $frontendDir\out" }
else { throw "Build finished but out\index.html is missing." }
