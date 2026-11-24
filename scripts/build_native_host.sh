#!/usr/bin/env bash
# Copy the complete helper directory to Contents/Helpers in the native app.
# Its private runtime needs neither Qt nor a Python installation on the user's Mac.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  printf '%s\n' 'Falta Python de construcción. Crea .venv e instala .[dev] y PyInstaller.' >&2
  exit 1
fi
"$PYTHON_BIN" -m PyInstaller --noconfirm --clean \
  --workpath "$PROJECT_DIR/build/native-helper-work" \
  --distpath "$PROJECT_DIR/build/native-helper" \
  "$PROJECT_DIR/packaging/native_host.spec"
printf '%s\n' "$PROJECT_DIR/build/native-helper/zeuz-agent-service"
