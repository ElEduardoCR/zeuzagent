# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

project = Path(SPECPATH).parent
datas = [
    (
        str(project / "src" / "zeuzagent" / "qml" / "Main.qml"),
        "zeuzagent/qml",
    ),
    (str(project / "src" / "zeuzagent" / "assets"), "zeuzagent/assets"),
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

if sys.platform == "darwin":
    # A macOS app is a directory bundle. Keeping dependencies outside the
    # executable avoids the slow one-file extraction step at every launch.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="ZeuzAgent",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        name="ZeuzAgent",
    )
    app = BUNDLE(
        collected,
        name="Zeuz Agent.app",
        icon=str(project / "src" / "zeuzagent" / "assets" / "AppIcon.icns"),
        bundle_identifier="com.zeuz.agent",
        version="0.4.1",
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="ZeuzAgent",
        icon=str(project / "src" / "zeuzagent" / "assets" / "AppIcon.ico") if sys.platform == "win32" else None,
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
