<#
.SYNOPSIS
  Build the PriorStates Windows installer (.exe) with Inno Setup.

.DESCRIPTION
  Builds the wheel, copies it into build\windows\, then compiles
  packaging\windows\priorstates.iss with Inno Setup's ISCC to produce
  build\windows\PriorStates-<ver>-Setup.exe.

  Prerequisites (Windows):
    - Python 3.10+ with the `build` package  (py -3 -m pip install build)
    - Inno Setup 6                            (https://jrsoftware.org/isdl.php)

.EXAMPLE
  packaging\windows\build-installer.ps1
#>
[CmdletBinding()]
param([string]$Python = "py")

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Out  = Join-Path $Root "build\windows"
New-Item -ItemType Directory -Force -Path $Out | Out-Null

# Version from pyproject.toml.
$ver = (Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
Write-Host "==> PriorStates $ver"

# 1) Build the wheel.
Write-Host "==> building wheel"
$pyArgs = @()
if ($Python -eq "py") { $pyArgs = @("-3") }
& $Python @pyArgs -m pip install -q --upgrade build | Out-Null
& $Python @pyArgs -m build --wheel --outdir $Out $Root
$wheel = (Get-ChildItem $Out -Filter "priorstates-$ver-*.whl" | Select-Object -First 1).Name
if (-not $wheel) { throw "wheel not found in $Out" }
Write-Host "    $wheel"

# 2) Find Inno Setup's compiler (ISCC).
$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
  foreach ($p in @(
      "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
      "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $p) { $iscc = $p; break }
  }
}
if (-not $iscc) { throw "Inno Setup (ISCC.exe) not found. Install Inno Setup 6 from https://jrsoftware.org/isdl.php" }

# 3) Compile the installer.
Write-Host "==> compiling installer with $iscc"
& $iscc "/DMyAppVersion=$ver" "/DWheel=$wheel" (Join-Path $PSScriptRoot "priorstates.iss")

$setup = Join-Path $Out "PriorStates-$ver-Setup.exe"
if (Test-Path $setup) { Write-Host "`nDone -> $setup" -ForegroundColor Green }
else { throw "installer not produced" }
