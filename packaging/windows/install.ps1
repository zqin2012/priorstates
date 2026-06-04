<#
.SYNOPSIS
  PriorStates installer for Windows (pip-based, no build toolchain required).

.DESCRIPTION
  Installs the package, initializes data dirs, optionally downloads the model
  and wires your AI agents, and creates Start Menu + Desktop shortcuts for the
  desktop GUI.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
  powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1 -Extras -Model -Wire

.NOTES
  Requires Python >= 3.10 on PATH (or pass -Python).  Node.js is optional
  (needed only for the cockpit web UI).
#>
[CmdletBinding()]
param(
  [switch]$Extras,            # also install onnxruntime + mcp + pandas extras
  [switch]$Model,            # also download the semantic embedding model
  [switch]$Wire,             # also run `priorstates agents install`
  [switch]$NoShortcuts,      # skip Start Menu / Desktop shortcuts
  [string]$Python            # explicit python.exe to use
)

$ErrorActionPreference = "Stop"
# Repo root is two levels up from packaging\windows\.
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

function Find-Python {
  if ($Python) { return $Python }
  # Prefer the py launcher (handles multiple versions); fall back to python.exe.
  if (Get-Command py -ErrorAction SilentlyContinue) { return "py -3" }
  if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
  throw "Python 3.10+ not found. Install it from https://python.org (tick 'Add to PATH') and retry."
}

$Py = Find-Python
Write-Host "==> using Python: $Py"
# Invoke helper: `& $exe $args` where $Py may be "py -3".
$PyParts = $Py.Split(" ")
$PyExe   = $PyParts[0]
$PyPre   = @($PyParts[1..($PyParts.Length-1)])
function Py { & $PyExe @PyPre @args }

# Confirm version >= 3.10.
$ver = (Py -c "import sys;print('%d.%d'%sys.version_info[:2])").Trim()
if ([version]$ver -lt [version]"3.10") { throw "Python $ver is too old; need >= 3.10." }

$Spec = if ($Extras) { "$Root[full]" } else { $Root }

Write-Host "==> ensuring modern build tooling"
try { Py -m pip install -q --upgrade pip setuptools wheel | Out-Null }
catch { Write-Warning "could not upgrade build tooling; continuing" }

# Clean any prior bad install (a pre-PEP621 setuptools builds an empty UNKNOWN).
Py -m pip uninstall -y UNKNOWN  2>$null | Out-Null
Py -m pip uninstall -y priorstates 2>$null | Out-Null

Write-Host "==> installing priorstates ($Spec)"
if (Get-Command pipx -ErrorAction SilentlyContinue) {
  pipx install --force $Root
  if ($Extras) { pipx inject priorstates onnxruntime tokenizers mcp pyyaml pandas jupyter_client ipykernel }
} else {
  Py -m pip install --upgrade --force-reinstall $Spec
}

if ((Py -c "import priorstates" 2>$null; $LASTEXITCODE) -ne 0) {
  Write-Error @"
priorstates did not import after install. Your Python's build tooling is likely
too old to read pyproject metadata. Upgrade and retry:
    $Py -m pip install --upgrade pip setuptools wheel
    $Py -m pip install --force-reinstall "$Spec"
Meanwhile you can run everything with:
    $Py -m priorstates <command>
"@
  exit 1
}

Write-Host "==> priorstates init"
Py -m priorstates init
if ($Model) { Write-Host "==> downloading embedding model"; Py -m priorstates init --download-model }
if ($Wire)  { Write-Host "==> wiring agents";                Py -m priorstates agents install }

# Locate the Scripts dir holding priorstates.exe / priorstates-gui.exe.
$Scripts = (Py -c "import sysconfig;print(sysconfig.get_path('scripts'))").Trim()
$GuiExe  = Join-Path $Scripts "priorstates-gui.exe"
$CliExe  = Join-Path $Scripts "priorstates.exe"

if (-not $NoShortcuts) {
  if (Test-Path $GuiExe) {
    Write-Host "==> creating shortcuts"
    $ws = New-Object -ComObject WScript.Shell
    foreach ($dir in @(
        [Environment]::GetFolderPath("Programs"),
        [Environment]::GetFolderPath("Desktop"))) {
      $lnk = $ws.CreateShortcut((Join-Path $dir "PriorStates.lnk"))
      $lnk.TargetPath = $GuiExe
      $lnk.IconLocation = $GuiExe
      $lnk.Description = "PriorStates - shared memory & research journal for your AI agents"
      $lnk.Save()
    }
  } else {
    # priorstates-gui.exe not found (e.g. a non-standard scripts dir) -- let the
    # CLI build the Start Menu + Desktop shortcut itself (pythonw -m priorstates gui).
    Write-Host "==> creating shortcuts (via install-launcher)"
    Py -m priorstates install-launcher --desktop
  }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
if (Test-Path $CliExe) {
  $onPath = ($env:Path -split ";") -contains $Scripts
  if ($onPath) { Write-Host "  priorstates <command>            # on your PATH" }
  else { Write-Host "  Add to PATH for the bare command:  setx PATH `"$Scripts;%PATH%`"" }
}
Write-Host "  $Py -m priorstates <command>     # always works"
Write-Host ""
Write-Host "Try:"
Write-Host "  $Py -m priorstates doctor"
Write-Host "  $Py -m priorstates gui"
Write-Host "  $Py -m priorstates cockpit       # -> http://127.0.0.1:7700 (needs Node.js)"
if (-not $Wire) { Write-Host "  $Py -m priorstates agents install" }
