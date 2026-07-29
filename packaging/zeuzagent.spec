# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

project = Path(SPECPATH).parent
datas = [
    (
        str(project / "src" / "zeuzagent" / "qml" / "Main.qml"),
        "zeuzagent/qml",
    )
]

a = Analysis(
    [str(project / "packaging" / "desktop_entry.py")],
    pathex=[str(project / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["zeroconf", "ifaddr"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ZeuzAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="Zeuz Agent.app",
        bundle_identifier="com.zeuz.agent",
    )
