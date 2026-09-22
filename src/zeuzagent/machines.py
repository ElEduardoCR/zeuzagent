from __future__ import annotations

import json
import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any


class MachineError(ValueError):
    pass


class MachineConflict(MachineError):
    status = 409


_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class MachineRegistry:
    """Persistent source of truth for CNC and Orange Pi assignments."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with _LOCKS_GUARD:
            self._lock = _LOCKS.setdefault(str(path.resolve()), threading.RLock())

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            try:
                with self.path.open("r", encoding="utf-8") as handle:
                    value = json.load(handle)
            except FileNotFoundError:
                return []
            except (json.JSONDecodeError, OSError) as exc:
                raise MachineError("No se pudo leer el registro de máquinas; se conserva sin cambios") from exc
            machines = value.get("machines", []) if isinstance(value, dict) else []
            return [dict(machine) for machine in machines if isinstance(machine, dict)]

    def get(self, machine_id: str | None) -> dict[str, Any] | None:
        return next((machine for machine in self.list() if machine.get("id") == machine_id), None)

    def save(self, value: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            machines = self.list()
            machine_id = str(value.get("id", "")).strip()
            existing_machine = next(
                (machine for machine in machines if machine.get("id") == machine_id), None
            )
            if existing_machine and "revision" in value and value["revision"] != existing_machine.get("revision", 0):
                raise MachineConflict("El perfil cambió en otro equipo. Actualiza la lista y revisa los cambios antes de guardar.")
            # Mobile clients edit only the serial profile. Preserve the Orange
            # Pi assignment, which is managed by the desktop agent.
            candidate = dict(value)
            if existing_machine:
                candidate.setdefault("dnc_host", existing_machine.get("dnc_host", ""))
                candidate.setdefault("dnc_port", existing_machine.get("dnc_port", 5000))
                candidate.setdefault("dnc_machine_id", existing_machine.get("dnc_machine_id", ""))
            clean = validate_machine(candidate)
            # A content revision is portable between Agent and Pi. Independent
            # counters can accidentally match after a mobile connection switches.
            fields = {key: item for key, item in clean.items() if not key.startswith("dnc_")}
            clean["revision"] = int(hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:13], 16)
            if machine_id:
                for index, machine in enumerate(machines):
                    if machine.get("id") == machine_id:
                        clean["id"] = machine_id
                        machines[index] = clean
                        self._write(machines)
                        return clean
                clean["id"] = machine_id
            else:
                existing = {str(machine.get("id", "")) for machine in machines}
                base = _slugify(clean["name"])
                machine_id = base
                suffix = 2
                while machine_id in existing:
                    machine_id = f"{base}-{suffix}"
                    suffix += 1
                clean["id"] = machine_id
            machines.append(clean)
            self._write(machines)
            return clean

    def delete(self, machine_id: str) -> None:
        with self._lock:
            machines = self.list()
            remaining = [machine for machine in machines if machine.get("id") != machine_id]
            if len(remaining) == len(machines):
                raise MachineError("Máquina no encontrada")
            self._write(remaining)

    def _write(self, machines: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump({"machines": machines}, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, self.path)


def validate_machine(value: dict[str, Any]) -> dict[str, Any]:
    name = str(value.get("name", "")).strip()
    if not name:
        raise MachineError("El nombre de la máquina es obligatorio")
    host = str(value.get("dnc_host", value.get("host", ""))).strip().rstrip("/")
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE).split("/", 1)[0]
    if ":" in host and host.count(":") == 1:
        possible_host, possible_port = host.rsplit(":", 1)
        if possible_port.isdigit():
            host = possible_host
            value = {**value, "dnc_port": int(possible_port)}
    if not host:
        raise MachineError("Asocia una Orange Pi a la máquina")

    def integer(key: str, default: int, allowed: set[int] | None = None) -> int:
        try:
            result = int(value.get(key, default))
        except (TypeError, ValueError) as exc:
            raise MachineError(f"El valor de {key} no es válido") from exc
        if result <= 0 or (allowed is not None and result not in allowed):
            raise MachineError(f"El valor de {key} no es válido")
        return result

    dnc_port = integer("dnc_port", 5000)
    if dnc_port > 65535:
        raise MachineError("El puerto de la Orange Pi no es válido")
    parity = str(value.get("parity", "N")).upper()
    flow = str(value.get("flow_control", "xonxoff")).lower()
    terminator = str(value.get("line_terminator", "CRLF")).upper()
    if parity not in {"N", "E", "O", "M", "S"}:
        raise MachineError("La paridad no es válida")
    if flow not in {"xonxoff", "rtscts", "none"}:
        raise MachineError("El control de flujo no es válido")
    if terminator not in {"CR", "CRLF", "LF"}:
        raise MachineError("El terminador de línea no es válido")
    return {
        "name": name,
        "dnc_host": host,
        "dnc_port": dnc_port,
        "dnc_machine_id": str(value.get("dnc_machine_id", "")),
        "baudrate": integer("baudrate", 9600),
        "bytesize": integer("bytesize", 8, {5, 6, 7, 8}),
        "parity": parity,
        "stopbits": integer("stopbits", 1, {1, 2}),
        "flow_control": flow,
        "line_terminator": terminator,
        "dtr": bool(value.get("dtr", False)),
        "rts": bool(value.get("rts", False)),
        "dripfeed": bool(value.get("dripfeed", False)),
    }


def serial_profile(machine: dict[str, Any]) -> dict[str, Any]:
    """Fields understood by ZeuzDNC; routing details remain in the agent."""
    return {
        key: (machine.get("dnc_machine_id") or machine[key]) if key == "id" else machine[key]
        for key in (
            "id", "name", "baudrate", "bytesize", "parity", "stopbits",
            "flow_control", "line_terminator", "dtr", "rts", "dripfeed",
        )
        if key in machine
    }


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "maquina"
