# -*- mode: python ; coding: utf-8 -*-
import sys
import ssl
from pathlib import Path

project = Path(SPECPATH).parent
datas = [
    (
        str(project / "src" / "zeuzagent" / "qml" / "Main.qml"),
        "zeuzagent/qml",
    ),
    (str(project / "src" / "zeuzagent" / "assets"), "zeuzagent/assets"),
]
# Some managed Python runtimes add a trust-store file beside ssl.py. Preserve
# that runtime's verification behavior in the frozen executable when present.
runtime_trust_store = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
if runtime_trust_store.is_file():
    datas.append((str(runtime_trust_store), "."))

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
        version="0.5.0",
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
