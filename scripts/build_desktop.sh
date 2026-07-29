#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_DIR"

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install -e '.[package]'
.venv/bin/python -m PyInstaller --noconfirm --clean packaging/zeuzagent.spec

if [ -d "dist/Zeuz Agent.app" ]; then
    printf '\nZeuz Agent listo en dist/Zeuz Agent.app\n'
else
    if command -v sha256sum >/dev/null 2>&1; then
        (cd dist && sha256sum ZeuzAgent >ZeuzAgent.sha256)
    else
        (cd dist && shasum -a 256 ZeuzAgent >ZeuzAgent.sha256)
    fi
    printf '\nZeuz Agent listo en dist/ZeuzAgent\n'
fi
