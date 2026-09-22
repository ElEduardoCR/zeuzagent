from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from .config import AgentConfig, default_config_path, load_or_create_config
from .runtime import AgentRuntime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zeuzagent", description="Puente local de Zeuz")
    parser.add_argument("--config", type=Path, default=default_config_path())
    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser("init", help="crear la configuración inicial")
    init.add_argument("--programs-dir", type=Path)
    init.add_argument("--name")
    init.add_argument("--force", action="store_true")

    subparsers.add_parser("run", help="iniciar el agente")
    subparsers.add_parser("ui", help="abrir la aplicación de escritorio")
    subparsers.add_parser("show-config", help="mostrar ubicación y datos no secretos")
    return parser


def _init(path: Path, programs_dir: Path | None, name: str | None, force: bool) -> int:
    if path.exists() and not force:
        print(f"Ya existe una configuración en {path}")
        print("Usa --force solo si deseas reemplazar sus credenciales.")
        return 2
    config = AgentConfig.create(programs_dir=programs_dir, name=name)
    Path(config.programs_dir).mkdir(parents=True, exist_ok=True)
    config.save(path)
    print(f"Configuración creada: {path}")
    print(f"Carpeta de programas: {config.programs_dir}")
    print(f"Código de emparejamiento: {config.pairing_code}")
    return 0


def _load_or_create(path: Path) -> AgentConfig:
    config, _, created = load_or_create_config(path)
    if created:
        print(f"Configuración creada: {path}")
        print(f"Código de emparejamiento: {config.pairing_code}")
    return config


def _run(path: Path) -> int:
    config = _load_or_create(path)
    runtime = AgentRuntime(config, path.with_name("machines.json"))
    runtime.start()
    print(f"{config.name} escuchando en http://{config.host}:{config.port}")
    print(f"Carpeta de programas: {config.programs_dir}")
    print("Descubrimiento mDNS: " + ("activo" if runtime.discovery_active else "no disponible"))
    try:
        while True:
            threading.Event().wait(3600)
    except KeyboardInterrupt:
        print("\nDeteniendo Zeuz Agent…")
    finally:
        runtime.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    command = args.command or "run"
    if command == "init":
        return _init(args.config, args.programs_dir, args.name, args.force)
    if command == "show-config":
        config = _load_or_create(args.config)
        print(f"Configuración: {args.config}")
        print(f"Nombre: {config.name}")
        print(f"Carpeta: {config.programs_dir}")
        print(f"Puerto: {config.port}")
        print(f"Código de emparejamiento: {config.pairing_code}")
        return 0
    if command == "ui":
        try:
            from .desktop import main as desktop_main
        except ImportError as exc:
            raise SystemExit(
                "Falta PySide6. Instala la interfaz con: pip install -e \".[desktop]\""
            ) from exc
        return desktop_main(["--config", str(args.config)])
    return _run(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
