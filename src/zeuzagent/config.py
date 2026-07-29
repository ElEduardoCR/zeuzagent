from __future__ import annotations

import json
import os
import platform
import secrets
from dataclasses import asdict, dataclass
from pathlib import Path


def default_config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "Zeuz" / "Agent" / "config.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Zeuz" / "Agent" / "config.json"
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "zeuz" / "agent.json"


def default_programs_dir() -> Path:
    return Path.home() / "Documents" / "Zeuz Programs"


@dataclass(frozen=True)
class AgentConfig:
    name: str
    programs_dir: str
    host: str = "0.0.0.0"
    port: int = 47820
    api_token: str = ""
    pairing_code: str = ""
    discovery: bool = True

    @classmethod
    def create(cls, programs_dir: Path | None = None, name: str | None = None) -> "AgentConfig":
        computer_name = platform.node().strip() or "Computadora"
        return cls(
            name=name or f"Zeuz Agent - {computer_name}",
            programs_dir=str((programs_dir or default_programs_dir()).expanduser().resolve()),
            api_token=secrets.token_urlsafe(32),
            pairing_code=f"{secrets.randbelow(1_000_000):06d}",
        )

    @classmethod
    def load(cls, path: Path) -> "AgentConfig":
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        config = cls(**data)
        if not config.api_token or not config.pairing_code:
            raise ValueError("La configuración no contiene credenciales válidas")
        if not 1 <= config.port <= 65535:
            raise ValueError("El puerto configurado no es válido")
        return config

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(asdict(self), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def load_or_create_config(path: Path | None = None) -> tuple[AgentConfig, Path, bool]:
    """Load the persisted configuration, creating secure defaults when absent."""
    target = path or default_config_path()
    if target.exists():
        return AgentConfig.load(target), target, False
    config = AgentConfig.create()
    Path(config.programs_dir).mkdir(parents=True, exist_ok=True)
    config.save(target)
    return config, target, True
