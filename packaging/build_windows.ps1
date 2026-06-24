# Build a self-contained yap.exe on Windows (PyInstaller).
#   powershell -ExecutionPolicy Bypass -File .\packaging\build_windows.ps1 [icon.png]
# Output: dist\yap\yap.exe  (a folder app; zip dist\yap for distribution).
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

# Pick a Python to freeze with (prefer a mature one).
$py = $env:YAP_BUILD_PY
if (-not $py) {
  foreach ($c in @("py -3.12", "py -3.11", "py -3", "python")) {
    $exe = ($c -split ' ')[0]
    if (Get-Command $exe -ErrorAction SilentlyContinue) { $py = $c; break }
  }
}
Write-Host "==> freezing with: $py"

$venv = Join-Path $root ".build-venv"
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
Invoke-Expression "$py -m venv `"$venv`""
$pip = Join-Path $venv "Scripts\pip.exe"
$vpy = Join-Path $venv "Scripts\python.exe"
& $pip install -U pip wheel | Out-Null
Write-Host "==> installing yap + build tools..."
& $pip install ".[full]" pyinstaller pillow | Out-Null

# Convert icon.png -> yap.ico for the exe. Prefer the icon committed in the repo
# (self-contained builds), then an explicit arg, then the config dir.
$repoIcon = Join-Path $root "packaging\yap-icon.png"
$iconPng = if ($args.Count -ge 1) { $args[0] }
           elseif (Test-Path $repoIcon) { $repoIcon }
           else { Join-Path $env:APPDATA "yap\icon.png" }
if (Test-Path $iconPng) {
  $ico = Join-Path $env:TEMP "yap.ico"
  & $vpy -c "from PIL import Image; Image.open(r'$iconPng').save(r'$ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
  $env:YAP_ICO = $ico
  Write-Host "==> icon: $ico"
} else {
  Write-Host "==> no icon at $iconPng (run 'yap icon <file>' first); building without one"
}

if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist)  { Remove-Item -Recurse -Force dist }
& $vpy -m PyInstaller packaging\yap.spec --noconfirm

Write-Host ""
Write-Host "OK  built dist\yap\yap.exe"
Write-Host "Run it, or add a shortcut to your Startup folder to launch at login."
