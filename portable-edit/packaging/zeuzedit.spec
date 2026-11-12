# Standalone Windows/Linux directory. Build on the target operating system.
import sys
import ssl
from pathlib import Path

project = Path(SPECPATH).parent
ssl_policy = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
runtime_data = [(str(ssl_policy), ".")] if ssl_policy.is_file() else []
a = Analysis(
    [str(project / "packaging" / "entry.py")],
    pathex=[str(project / "src")],
    datas=[(str(project / "src" / "zeuzedit_desktop" / "assets"), "zeuzedit_desktop/assets")] + runtime_data,
    hiddenimports=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore", "PySide6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="ZeuzEdit", debug=False, console=False,
    icon=str(project / "src" / "zeuzedit_desktop" / "assets" / "AppIcon.png") if sys.platform == "win32" else None,
    upx=False,
)
collection = COLLECT(exe, a.binaries, a.datas, name="ZeuzEdit", upx=False)
