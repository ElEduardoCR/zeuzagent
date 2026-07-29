from __future__ import annotations

import os
import platform
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path


APP_ID = "com.zeuz.agent"
WINDOWS_VALUE = "ZeuzAgent"


def launch_arguments() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimized"]
    executable = Path(sys.executable)
    if platform.system() == "Windows":
        pythonw = executable.with_name("pythonw.exe")
        if pythonw.exists():
            executable = pythonw
    return [str(executable), "-m", "zeuzagent.desktop", "--minimized"]


def is_enabled() -> bool:
    system = platform.system()
    if system == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as key:
                winreg.QueryValueEx(key, WINDOWS_VALUE)
            return True
        except (FileNotFoundError, OSError):
            return False
    if system == "Darwin":
        return _mac_path().exists()
    return _linux_path().exists()


def set_enabled(enabled: bool) -> None:
    system = platform.system()
    if system == "Windows":
        _set_windows(enabled)
    elif system == "Darwin":
        _set_macos(enabled)
    else:
        _set_linux(enabled)


def _set_windows(enabled: bool) -> None:
    import winreg

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                WINDOWS_VALUE,
                0,
                winreg.REG_SZ,
                subprocess.list2cmdline(launch_arguments()),
            )
        else:
            try:
                winreg.DeleteValue(key, WINDOWS_VALUE)
            except FileNotFoundError:
                pass


def _mac_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


def _set_macos(enabled: bool) -> None:
    target = _mac_path()
    if not enabled:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": APP_ID,
        "ProgramArguments": launch_arguments(),
        "RunAtLoad": True,
        "KeepAlive": False,
    }
    with target.open("wb") as handle:
        plistlib.dump(payload, handle)


def _linux_path() -> Path:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_home / "autostart" / "zeuz-agent.desktop"


def _set_linux(enabled: bool) -> None:
    target = _linux_path()
    if not enabled:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    command = " ".join(shlex.quote(value) for value in launch_arguments())
    target.write_text(
        "\n".join(
            (
                "[Desktop Entry]",
                "Type=Application",
                "Name=Zeuz Agent",
                f"Exec={command}",
                "Terminal=false",
                "X-GNOME-Autostart-enabled=true",
                "",
            )
        ),
        encoding="utf-8",
    )
