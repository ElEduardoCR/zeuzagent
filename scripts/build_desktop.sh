#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_DIR"

if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
fi

.venv/bin/python -m pip install -e '.[package]'
.venv/bin/python -m unittest discover -s tests -q
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
    if [ "$(uname -s)" = Linux ]; then
        LINUX_ARCH=$(uname -m)
        LINUX_PACKAGE="ZeuzAgent-linux-$LINUX_ARCH"
        LINUX_STAGE="build/$LINUX_PACKAGE"
        mkdir -p "$LINUX_STAGE"
        cp dist/ZeuzAgent "$LINUX_STAGE/ZeuzAgent"
        cp src/zeuzagent/assets/app.png "$LINUX_STAGE/zeuzagent.png"
        cp packaging/linux/install.sh packaging/linux/README.txt "$LINUX_STAGE/"
        chmod +x "$LINUX_STAGE/ZeuzAgent" "$LINUX_STAGE/install.sh"
        tar -czf "dist/$LINUX_PACKAGE.tar.gz" -C build "$LINUX_PACKAGE"
        (cd dist && sha256sum "$LINUX_PACKAGE.tar.gz" > "$LINUX_PACKAGE.tar.gz.sha256")
        printf '\nPaquete Linux listo en dist/%s.tar.gz\n' "$LINUX_PACKAGE"
    fi
fi
