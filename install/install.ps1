# yap installer for Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File .\install\install.ps1
$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root
Write-Host "yap installer"
Write-Host "  project: $root"

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python 3.9+ not found. Install it from python.org first." }

Write-Host "  installing with pip..."
& $py.Path -m pip install --user ".[full]"

Write-Host ""
Write-Host "Done. Try:  yap run"
Write-Host "Tip: add a shortcut to 'yap run' in your Startup folder to launch on login."
