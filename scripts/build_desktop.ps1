$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot ".."))

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
}

& ".venv\Scripts\python.exe" -m pip install -e ".[package]"
& ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean packaging\zeuzagent.spec

$hash = (Get-FileHash "dist\ZeuzAgent.exe" -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "dist\ZeuzAgent.exe.sha256" `
    -Value "$hash  ZeuzAgent.exe" -Encoding ascii

Write-Host ""
Write-Host "Zeuz Agent listo en dist\ZeuzAgent.exe"
