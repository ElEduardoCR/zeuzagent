$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo preparar Python" }
}

& ".venv\Scripts\python.exe" -m pip install -e ".[package]"
if ($LASTEXITCODE -ne 0) { throw "No se pudieron instalar las dependencias" }
& ".venv\Scripts\python.exe" -m unittest discover -s tests -q
if ($LASTEXITCODE -ne 0) { throw "Las pruebas no pasaron; no se generó un instalador nuevo" }
& ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean packaging\zeuzagent.spec
if ($LASTEXITCODE -ne 0) { throw "No se pudo compilar Zeuz Agent" }
if (-not (Test-Path "dist\ZeuzAgent.exe")) { throw "No se generó dist\ZeuzAgent.exe" }

$hash = (Get-FileHash "dist\ZeuzAgent.exe" -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "dist\ZeuzAgent.exe.sha256" `
    -Value "$hash  ZeuzAgent.exe" -Encoding ascii

Write-Host ""
Write-Host "Zeuz Agent listo en dist\ZeuzAgent.exe"
