#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Linux ]; then
  echo "Este paquete debe compilarse en Linux." >&2
  exit 2
fi
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[package]'
.venv/bin/python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen .venv/bin/python -m zeuzedit_desktop --smoke-test
.venv/bin/python -m PyInstaller --noconfirm packaging/zeuzedit.spec
echo "Aplicación: dist/ZeuzEdit/ZeuzEdit (conservar toda la carpeta)"
