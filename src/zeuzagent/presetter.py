"""Authenticated Presetter presence and upload validation (no serial actions)."""
from __future__ import annotations

import re
import threading
import time
from typing import Callable

from .library import LibraryError

PRESENCE_TTL = 90
MAX_OFFSETS_BYTES = 512 * 1024
CAPABILITIES = {
    "presetter": True,
    "presetter_api": 1,
    "presetter_upload": "library_only",
}


class PresetterClients:
    """Presence is volatile; an expired or restarted client is never 'connected'."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._clients: dict[str, dict] = {}

    def register(self, body: dict, address: str) -> dict:
        client_id = body.get("client_id", "")
        name = body.get("name", "ZeuzPresetter")
        version = body.get("version", "")
        if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", client_id):
            raise LibraryError("El identificador del Presetter no es válido")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise LibraryError("El nombre del Presetter no es válido")
        if not isinstance(version, str) or len(version) > 40:
            raise LibraryError("La versión del Presetter no es válida")
        capabilities = body.get("capabilities", [])
        if not isinstance(capabilities, list) or len(capabilities) > 12 or any(
            not isinstance(item, str) or len(item) > 60 for item in capabilities
        ):
            raise LibraryError("Las capacidades del Presetter no son válidas")
        client = {
            "client_id": client_id, "name": name.strip(), "version": version,
            "address": address, "capabilities": capabilities,
        }
        with self._lock:
            self._prune()
            if client_id not in self._clients and len(self._clients) >= 64:
                raise LibraryError("Se alcanzó el límite de Presetters activos")
            self._clients[client_id] = {**client, "last_seen": self._clock()}
        return {"ok": True, "client": client, "presence_ttl": PRESENCE_TTL}

    def _prune(self) -> None:
        cutoff = self._clock() - PRESENCE_TTL
        self._clients = {key: item for key, item in self._clients.items() if item["last_seen"] > cutoff}

    def list(self) -> list[dict]:
        with self._lock:
            self._prune()
            return sorted(
                [{key: value for key, value in item.items() if key != "last_seen"} for item in self._clients.values()],
                key=lambda item: item["name"].casefold(),
            )


def validate_upload(body: dict) -> tuple[str, str, str]:
    """Accept ASCII CNC text; do not silently replace unsupported characters."""
    machine_id = body.get("machine_id", "")
    filename = body.get("filename", "")
    content = body.get("content", "")
    if not isinstance(machine_id, str) or not machine_id:
        raise LibraryError("Selecciona la máquina destino")
    if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.(?:txt|nc|tap)", filename, re.IGNORECASE):
        raise LibraryError("Usa un nombre simple con extensión .txt, .nc o .tap")
    if not isinstance(content, str) or not content.strip():
        raise LibraryError("El archivo de seteos está vacío")
    try:
        raw = content.encode("ascii")
    except UnicodeEncodeError as exc:
        raise LibraryError("Los seteos deben usar texto ASCII para la CNC") from exc
    if any(byte < 32 and byte not in {9, 10, 13} for byte in raw) or 127 in raw:
        raise LibraryError("El archivo contiene caracteres de control no permitidos")
    if len(raw) > MAX_OFFSETS_BYTES:
        raise LibraryError("El archivo de seteos supera 512 KB")
    return machine_id, filename, content
