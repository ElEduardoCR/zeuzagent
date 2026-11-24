#!/usr/bin/env sh
# Instalación por usuario, sin sudo y sin cambiar programas ni configuración.
set -eu
PACKAGE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/zeuzagent"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APP_DIR" "$DESKTOP_DIR"
install -m 755 "$PACKAGE_DIR/ZeuzAgent" "$APP_DIR/ZeuzAgent"
install -m 644 "$PACKAGE_DIR/zeuzagent.png" "$APP_DIR/zeuzagent.png"
printf '%s\n' '[Desktop Entry]' 'Type=Application' 'Name=Zeuz Agent' \
    "Exec=\"$APP_DIR/ZeuzAgent\"" "Icon=$APP_DIR/zeuzagent.png" \
    'Terminal=false' 'Categories=Utility;Development;' \
    'Comment=Biblioteca y envío de programas CNC ZEUZ' \
    > "$DESKTOP_DIR/zeuz-agent.desktop"
printf '\nZeuz Agent instalado en %s\nÁbrelo desde el menú de aplicaciones.\n' "$APP_DIR"
