<#
.SYNOPSIS
  Build the presentation: main-bizops.tex -> the-estimator.pdf + PNG previews

.DESCRIPTION
  Needs two portable tools:
    * tectonic  (LaTeX engine, fetches packages on demand)
    * pdftoppm  (Poppler, renders PDF pages to PNG)

  Lookup order for each tool:
    1. -Tectonic / -PopplerBin parameter
    2. $env:TECTONIC / $env:POPPLER_BIN
    3. PATH
    4. %LOCALAPPDATA%\Temp\opencode\... (portable install used on this machine)

.EXAMPLE
  .\build.ps1                          # main-bizops.tex -> the-estimator.pdf
  .\build.ps1 -Target main-bizops      # same source, explicitly selected
  .\build.ps1 -NoPreview               # compile only
  .\build.ps1 -Dpi 160                 # sharper previews
#>
[CmdletBinding()]
param(
  [string]$Target    = 'main-bizops',
  [string]$Tectonic   = $env:TECTONIC,
  [string]$PopplerBin = $env:POPPLER_BIN,
  [int]$Dpi           = 110,
  [switch]$NoPreview
)

$ErrorActionPreference = 'Stop'
$slides = $PSScriptRoot
$temp   = Join-Path $env:LOCALAPPDATA 'Temp\opencode'

function Resolve-Tool {
  param([string]$Name, [string[]]$Candidates)

  foreach ($c in $Candidates) {
    if ([string]::IsNullOrWhiteSpace($c)) { continue }
    if (Test-Path -LiteralPath $c) { return (Resolve-Path -LiteralPath $c).Path }
  }
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  throw "Could not find $Name. Pass -$($Name -replace '\.exe$','') or set an env var, or install it on PATH."
}

if (-not $Tectonic) {
  $Tectonic = Resolve-Tool 'tectonic.exe' @(
    (Join-Path $temp 'tectonic\tectonic.exe'),
    (Join-Path $slides 'tools\tectonic.exe')
  )
}

$popplerCandidates = @()
if ($PopplerBin) { $popplerCandidates += (Join-Path $PopplerBin 'pdftoppm.exe') }
$popplerCandidates += (Join-Path $slides 'tools\pdftoppm.exe')
$popplerCandidates += Get-ChildItem (Join-Path $temp 'poppler') -Recurse -Filter 'pdftoppm.exe' -ErrorAction SilentlyContinue |
  Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName

$pdftoppm = $null
if (-not $NoPreview) {
  $pdftoppm = Resolve-Tool 'pdftoppm.exe' $popplerCandidates
}

Push-Location $slides
try {
  $src  = Join-Path $slides "$Target.tex"
  $buildDir = Join-Path $temp "estimator-slides\$Target"
  New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
  $pdf  = Join-Path $buildDir "$Target.pdf"
  $log  = Join-Path $buildDir "$Target.log"
  if (-not (Test-Path $src)) { throw "Source not found: $src" }

  $before = if (Test-Path $pdf) { (Get-Item $pdf).LastWriteTimeUtc } else { [datetime]::MinValue }

  Write-Host "[1/2] tectonic $Target.tex" -ForegroundColor Cyan
  & $Tectonic -X compile "$Target.tex" --outdir $buildDir --keep-logs
  $code = $LASTEXITCODE

  $fresh = (Test-Path $pdf) -and ((Get-Item $pdf).LastWriteTimeUtc -gt $before)
  if (-not $fresh) {
    throw "Compile failed (exit $code) and $Target.pdf was not updated. See $Target.log above."
  }
  if ($code -ne 0) {
    Write-Host "      tectonic exited $code but wrote a fresh PDF (fontconfig noise); continuing." -ForegroundColor Yellow
  }

  $m = Select-String -Path $log -Pattern "Output written on $([regex]::Escape($Target))\.(?:pdf|xdv) \((\d+) pages?" |
    Select-Object -Last 1
  $pageInfo = if ($m) { "$($m.Matches[0].Groups[1].Value) pages" } else { 'page count unknown' }
  Write-Host "      $Target.pdf written: $([math]::Round((Get-Item $pdf).Length / 1KB)) KB, $pageInfo" -ForegroundColor Green

  # A single stable deliverable. Intermediates stay outside the repository.
  Copy-Item -LiteralPath $pdf -Destination (Join-Path $slides 'the-estimator.pdf') -Force

  if ($NoPreview) { return }

  $previewName = if ($Target -eq 'main') { 'current' } else { $Target }
  Write-Host "[2/2] pdftoppm -> preview\$previewName (${Dpi} dpi)" -ForegroundColor Cyan
  $out = Join-Path $slides "preview\$previewName"
  New-Item -ItemType Directory -Force -Path $out | Out-Null
  Get-ChildItem $out -Filter '*.png' -ErrorAction SilentlyContinue | Remove-Item -Force

  & $pdftoppm -png -r $Dpi $pdf (Join-Path $out 'slide')
  if ($LASTEXITCODE -ne 0) { throw "pdftoppm failed (exit $LASTEXITCODE)" }

  $png = Get-ChildItem $out -Filter '*.png'
  Write-Host "      $($png.Count) PNGs in preview\$previewName" -ForegroundColor Green
}
finally {
  Pop-Location
}
