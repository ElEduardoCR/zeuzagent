$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".venv/Scripts/python.exe")) { py -3 -m venv .venv }
& .venv/Scripts/python.exe -m pip install -e ".[package]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .venv/Scripts/python.exe -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& .venv/Scripts/python.exe -m PyInstaller --noconfirm packaging/zeuzedit.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Aplicación: dist/ZeuzEdit/ZeuzEdit.exe (conservar toda la carpeta)"
