# Run The Estimator API on Windows (PowerShell port of scripts/run_api.sh).
#
# Usage:
#   .\scripts\run_api.ps1                    # 127.0.0.1:8000 (auto-uses backend\.venv)
#   $env:HOST="0.0.0.0"; $env:PORT=8080; .\scripts\run_api.ps1
#   .\scripts\run_api.ps1 --reload           # extra args are forwarded to uvicorn
#
# The Python interpreter can be overridden with $env:PYTHON=/path/to/python.exe
# The UI is served from frontend\out when it exists (build it with
# .\frontend\build.ps1); without it the server runs API-only.
#
# Portable tools under %LOCALAPPDATA%\Temp\opencode are prepended to PATH when
# present: Codebase Lab shells out to `git` (see HANDOFF.md section 3).

$ErrorActionPreference = "Stop"

$backendDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Optional portable toolchain (MinGit / Node) used on this Windows box.
$portable = Join-Path $env:LOCALAPPDATA "Temp\opencode"
foreach ($rel in @("git\cmd", "nodejs")) {
    $candidate = Join-Path $portable $rel
    if (Test-Path $candidate) { $env:Path = "$candidate;$env:Path" }
}

if (-not $env:PYTHON) {
    $venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"
    $env:PYTHON = if (Test-Path $venvPython) { $venvPython } else { "python" }
}

$env:HOST = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$env:PORT = if ($env:PORT) { $env:PORT } else { "8000" }

Set-Location $backendDir
& $env:PYTHON -m uvicorn app.main:app --host $env:HOST --port $env:PORT @args
