# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import ssl

project = Path(SPECPATH).parent
# Some Python distributions load a companion trust-policy PEM from ssl.py.
# urllib constructs its HTTPS handler even for an HTTP URL, so this resource
# must remain beside the frozen module. Preserve the runtime's TLS policy.
ssl_policy = Path(ssl.__file__).with_name("codex-rejected-cas.pem")
runtime_data = [(str(ssl_policy), ".")] if ssl_policy.is_file() else []
analysis = Analysis(
    [str(project / "packaging" / "native_host_entry.py")],
    pathex=[str(project / "src")],
    hiddenimports=["zeroconf", "ifaddr"],
    excludes=["PySide6", "PyQt6", "tkinter", "unittest", "pytest"],
    datas=runtime_data, binaries=[], hookspath=[], runtime_hooks=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True,
    name="zeuz-agent-service", console=True, debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="zeuz-agent-service")
